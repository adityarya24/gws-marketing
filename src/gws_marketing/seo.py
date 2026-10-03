"""Deterministic on-page SEO audit of a public site; no Google auth, no LLM.

Everything here is read-only HTTP GET/HEAD. The network goes through one
injectable ``fetch`` callable so tests run without sockets. Redirects are
followed by hand (not by urllib) so every hop is visible: a chain of two or
more hops is itself a finding.

Severities are ``critical`` (blocks indexing or serves an error), ``warning``
(hurts snippets or crawl quality) and ``info`` (worth knowing). Every finding
carries a ``suggestion`` written so an agent can act on it directly.
"""
from __future__ import annotations

import ipaddress
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

USER_AGENT = "gws-marketing-seo-audit/0.3 (+read-only; https://github.com/adityarya24/gws-marketing)"
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 10
MAX_WORKERS = 5
DEFAULT_MAX_PAGES = 50
MAX_PAGES_CAP = 200
MAX_IMAGES = 30
MAX_SITEMAPS = 5
IMAGE_WARN_BYTES = 100 * 1024
TITLE_MAX = 60
DESCRIPTION_MIN = 50
DESCRIPTION_MAX = 160

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
_NOINDEX_RE = re.compile(r"(^|[\s,:])noindex($|[\s,])", re.IGNORECASE)


@dataclass
class Response:
    """One finished fetch, after any redirects were followed."""

    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    body: bytes = b""
    chain: list[str] = field(default_factory=list)

    @property
    def hops(self) -> int:
        return max(len(self.chain) - 1, 0)

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def size(self) -> int:
        length = self.headers.get("content-length", "")
        return int(length) if length.isdigit() else len(self.body)

    def text(self) -> str:
        match = re.search(r"charset=([\w-]+)", self.headers.get("content-type", ""), re.IGNORECASE)
        for encoding in (match.group(1) if match else "utf-8", "utf-8"):
            try:
                return self.body.decode(encoding, errors="replace")
            except LookupError:
                continue
        return self.body.decode("utf-8", errors="replace")


Fetcher = Callable[[str, str], Response]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _safe_url(url: str) -> str:
    """Percent-encode non-ASCII path/query (Hindi slugs) without double-encoding."""
    parts = urlsplit(url)
    return urlunsplit((
        parts.scheme,
        parts.netloc.encode("idna").decode("ascii") if not parts.netloc.isascii() else parts.netloc,
        quote(parts.path, safe="/%:@!$&'()*+,;=~-._"),
        quote(parts.query, safe="=&%:@!$'()*+,;/?~-._"),
        "",
    ))


def fetch_url(url: str, method: str = "GET") -> Response:
    """GET/HEAD with manual redirect following; raises on network failure."""
    chain = [url]
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        request = urllib.request.Request(
            _safe_url(current), method=method, headers={"User-Agent": USER_AGENT}
        )
        try:
            with _OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as reply:
                status, headers = reply.status, reply.headers
                body = b"" if method == "HEAD" else reply.read(MAX_BODY_BYTES)
        except urllib.error.HTTPError as exc:
            status, headers = exc.code, exc.headers
            body = b"" if method == "HEAD" else exc.read(MAX_BODY_BYTES)
        lowered = {key.lower(): value for key, value in headers.items()}
        location = lowered.get("location")
        if status in (301, 302, 303, 307, 308) and location:
            current = urljoin(current, location)
            chain.append(current)
            continue
        return Response(url, current, status, lowered, body, chain)
    raise RuntimeError(f"More than {MAX_REDIRECTS} redirects starting at {url}")


# --- HTML extraction -----------------------------------------------------------


class _PageParser(HTMLParser):
    """Collects the handful of tags the audit looks at."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.metas: list[dict[str, str]] = []
        self.canonical: str | None = None
        self.h1_count = 0
        self.images: list[dict[str, str | None]] = []
        self.jsonld: list[str] = []
        self._in_title = False
        self._title_parts: list[str] = []
        self._svg_depth = 0
        self._in_jsonld = False
        self._jsonld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag == "svg":
            self._svg_depth += 1
        elif tag == "title" and self._svg_depth == 0 and self.title is None:
            self._in_title = True
            self._title_parts = []
        elif tag == "meta":
            self.metas.append(values)
        elif tag == "link":
            rels = values.get("rel", "").lower().split()
            if "canonical" in rels and self.canonical is None:
                self.canonical = values.get("href", "")
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "img":
            self.images.append({
                "src": values.get("src") or None,
                "alt": values.get("alt") if "alt" in values else None,
            })
        elif tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._in_jsonld = True
            self._jsonld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "svg" and self._svg_depth:
            self._svg_depth -= 1
        elif tag == "title" and self._in_title:
            self._in_title = False
            self.title = _squash("".join(self._title_parts))
        elif tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self.jsonld.append("".join(self._jsonld_parts))

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        elif self._in_jsonld:
            self._jsonld_parts.append(data)

    def meta(self, name: str, attribute: str = "name") -> str | None:
        for values in self.metas:
            if values.get(attribute, "").lower() == name and "content" in values:
                return values["content"]
        return None


def _squash(text: str) -> str:
    return " ".join(text.split())


def _jsonld_types(blocks: list[str]) -> tuple[list[str], int]:
    """Return (@type names, count of blocks that are not valid JSON)."""
    types: list[str] = []
    invalid = 0

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            kind = node.get("@type")
            for name in kind if isinstance(kind, list) else [kind]:
                if isinstance(name, str) and name not in types:
                    types.append(name)
            walk(node.get("@graph"))

    for block in blocks:
        try:
            walk(json.loads(block))
        except ValueError:
            invalid += 1
    return types, invalid


# --- URL helpers ---------------------------------------------------------------


def _norm(url: str) -> str:
    """Comparison key: case-insensitive scheme/host, no fragment, no trailing slash."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _site_host(host: str) -> str:
    host = host.lower()
    return host.removeprefix("www.")


def _is_public_host(host: str) -> bool:
    """Keep the audit from poking at loopback or private addresses named in a page."""
    host = host.strip("[]").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return address.is_global


def _finding(severity: str, check: str, detail: str, suggestion: str) -> dict[str, str]:
    return {"severity": severity, "check": check, "detail": detail, "suggestion": suggestion}


# --- Site-level checks ---------------------------------------------------------


def _looks_like_html(response: Response) -> bool:
    head = response.body[:512].lstrip().lower()
    return "html" in response.content_type or head.startswith((b"<!doctype html", b"<html"))


def _check_robots(root: str, fetch: Fetcher, site: dict[str, Any]) -> RobotFileParser | None:
    """Fetch robots.txt, record findings, return a parser (None when unusable)."""
    robots_url = root + "robots.txt"
    findings = site["findings"]
    try:
        response = fetch(robots_url, "GET")
    except Exception as exc:  # noqa: BLE001 - a dead robots.txt must not stop the audit
        site["robots"] = {"url": robots_url, "exists": False}
        findings.append(_finding(
            "warning", "robots_unreachable", f"{robots_url} could not be fetched: {exc}",
            "Check that the host is reachable and serve a plain-text /robots.txt.",
        ))
        return None
    if response.status != 200 or _looks_like_html(response):
        # GitHub Pages and many SPAs answer a missing file with an HTML 404 page,
        # sometimes with a 200, so the body is judged as well as the status.
        kind = "an HTML page" if _looks_like_html(response) else "no file"
        site["robots"] = {"url": robots_url, "exists": False, "status": response.status}
        findings.append(_finding(
            "warning", "robots_missing",
            f"{robots_url} returned status {response.status} with {kind}, not a text robots.txt.",
            "Add /robots.txt as text/plain with at least 'User-agent: *', 'Allow: /' "
            "and a 'Sitemap:' line.",
        ))
        return None
    text = response.text()
    lines = text.splitlines()
    parser = RobotFileParser()
    parser.parse(lines)
    sitemaps = [
        line.split(":", 1)[1].strip()
        for line in lines
        if line.lower().startswith("sitemap:") and line.split(":", 1)[1].strip()
    ]
    site["robots"] = {"url": robots_url, "exists": True, "sitemaps": sitemaps}
    if not parser.can_fetch("*", root):
        findings.append(_finding(
            "critical", "robots_blocks_all",
            "robots.txt disallows the whole site ('Disallow: /') for all user agents.",
            "Remove 'Disallow: /' from the 'User-agent: *' group (or narrow it to the "
            "private paths) so search engines can crawl the site.",
        ))
    return parser


def _parse_sitemap(
    sitemap_url: str, fetch: Fetcher, site: dict[str, Any], max_urls: int
) -> list[str]:
    """Return page URLs from a sitemap or sitemap index, recording findings."""
    findings = site["findings"]
    urls: list[str] = []
    queue = [sitemap_url]
    seen: set[str] = set()
    parsed_any = False
    while queue and len(seen) < MAX_SITEMAPS and len(urls) < max_urls:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        try:
            response = fetch(current, "GET")
        except Exception as exc:  # noqa: BLE001
            findings.append(_finding(
                "warning", "sitemap_unreachable", f"{current} could not be fetched: {exc}",
                "Check that the sitemap URL is reachable.",
            ))
            continue
        if response.status != 200 or _looks_like_html(response):
            findings.append(_finding(
                "warning", "sitemap_missing",
                f"{current} returned status {response.status}"
                f"{' with an HTML page' if _looks_like_html(response) else ''}, not an XML sitemap.",
                "Publish an XML sitemap at this URL and reference it from robots.txt "
                "with a 'Sitemap:' line.",
            ))
            continue
        try:
            tree = ElementTree.fromstring(response.body)
        except ElementTree.ParseError as exc:
            findings.append(_finding(
                "warning", "sitemap_invalid", f"{current} is not valid XML: {exc}",
                "Regenerate the sitemap as well-formed XML (sitemaps.org schema).",
            ))
            continue
        parsed_any = True
        root_name = tree.tag.rsplit("}", 1)[-1]
        locs = [
            (element.text or "").strip()
            for element in tree.iter()
            if element.tag.rsplit("}", 1)[-1] == "loc" and (element.text or "").strip()
        ]
        if root_name == "sitemapindex":
            queue.extend(locs)
        elif root_name == "urlset":
            urls.extend(locs)
        else:
            findings.append(_finding(
                "warning", "sitemap_invalid",
                f"{current} has root element <{root_name}>, expected <urlset> or <sitemapindex>.",
                "Regenerate the sitemap using the sitemaps.org schema.",
            ))
    site["sitemap"] = {"url": sitemap_url, "parsed": parsed_any, "url_count": len(urls)}
    if parsed_any and not urls:
        findings.append(_finding(
            "warning", "sitemap_empty", f"{sitemap_url} parsed but lists no URLs.",
            "Add the site's indexable pages to the sitemap.",
        ))
    return list(dict.fromkeys(urls))


def _check_redirects(root: str, fetch: Fetcher, site: dict[str, Any]) -> None:
    """Probe http/https and www/non-www variants of the root host."""
    parts = urlsplit(root)
    host = parts.netloc
    alternate = host[4:] if host.startswith("www.") else f"www.{host}"
    variants = [f"http://{host}/", f"https://{host}/", f"http://{alternate}/", f"https://{alternate}/"]
    findings = site["findings"]
    results = []
    for variant in variants:
        try:
            response = fetch(variant, "GET")
        except Exception as exc:  # noqa: BLE001
            # The alternate host often has no DNS record at all; that is fine.
            results.append({"url": variant, "error": f"{type(exc).__name__}: {exc}"})
            continue
        results.append({
            "url": variant,
            "status": response.status,
            "hops": response.hops,
            "chain": response.chain,
            "final_url": response.final_url,
        })
        if response.hops >= 2:
            findings.append(_finding(
                "warning", "redirect_chain",
                f"{variant} takes {response.hops} redirect hops: {' -> '.join(response.chain)}.",
                "Redirect straight to the final canonical URL in a single 301 hop.",
            ))
        if (
            variant.startswith("http://")
            and response.status < 400
            and not response.final_url.startswith("https://")
        ):
            findings.append(_finding(
                "warning", "http_not_redirected",
                f"{variant} does not end on https (final URL {response.final_url}).",
                "301-redirect all http:// traffic to the https:// canonical host.",
            ))
    finals = {_norm(r["final_url"]) for r in results if r.get("status") == 200}
    if len(finals) > 1:
        findings.append(_finding(
            "warning", "host_variants_not_consolidated",
            "http/https and www/non-www variants end on different URLs: "
            + ", ".join(sorted(finals)) + ".",
            "Pick one canonical host and 301 every other variant to it.",
        ))
    site["redirects"] = results


# --- Page checks ---------------------------------------------------------------


def _audit_page(url: str, fetch: Fetcher) -> tuple[dict[str, Any], list[dict[str, str | None]]]:
    """Audit one page; returns (page record, image tags found). Never raises."""
    page: dict[str, Any] = {"url": url, "findings": []}
    findings = page["findings"]
    try:
        response = fetch(url, "GET")
    except Exception as exc:  # noqa: BLE001 - one bad page must not sink the audit
        findings.append(_finding(
            "critical", "fetch_failed", f"{url} could not be fetched: {type(exc).__name__}: {exc}",
            "Check that the URL loads; remove it from the sitemap if it is gone.",
        ))
        return page, []
    page.update(final_url=response.final_url, status=response.status, redirect_hops=response.hops)
    if response.hops >= 2:
        findings.append(_finding(
            "warning", "redirect_chain",
            f"{response.hops} redirect hops: {' -> '.join(response.chain)}.",
            "Link and list the final URL directly, and redirect in a single 301 hop.",
        ))
    elif response.hops == 1:
        findings.append(_finding(
            "info", "redirect",
            f"Redirects once to {response.final_url}.",
            "List the final URL in the sitemap instead of a redirecting one.",
        ))
    if response.status != 200:
        findings.append(_finding(
            "critical", "status_code", f"Final status is {response.status}, expected 200.",
            "Fix the page so it returns 200, or remove it from the sitemap.",
        ))
        return page, []

    header_robots = response.headers.get("x-robots-tag", "")
    if _NOINDEX_RE.search(header_robots):
        findings.append(_finding(
            "critical", "noindex_header", f"X-Robots-Tag header says '{header_robots}'.",
            "Remove 'noindex' from the X-Robots-Tag response header if this page should rank.",
        ))
    if not _looks_like_html(response):
        findings.append(_finding(
            "info", "not_html", f"Content-Type is '{response.content_type}'; HTML checks skipped.",
            "Nothing to do unless this URL should be an HTML page.",
        ))
        return page, []

    parser = _PageParser()
    try:
        parser.feed(response.text())
        parser.close()
    except Exception as exc:  # noqa: BLE001 - malformed markup is a finding, not a crash
        findings.append(_finding(
            "warning", "html_parse_error", f"HTML could not be fully parsed: {exc}",
            "Fix the malformed markup.",
        ))

    title = parser.title
    if not title:
        findings.append(_finding(
            "warning", "title_missing", "No <title> (or it is empty).",
            "Add a unique <title> of at most 60 characters.",
        ))
    elif len(title) > TITLE_MAX:
        findings.append(_finding(
            "warning", "title_too_long", f"Title is {len(title)} characters (max {TITLE_MAX}).",
            f"Shorten the title to {TITLE_MAX} characters or fewer, key words first.",
        ))

    # len() counts Unicode code points, so Hindi text is measured in characters, not bytes.
    description = parser.meta("description")
    description = _squash(description) if description is not None else None
    if not description:
        findings.append(_finding(
            "warning", "description_missing", "No meta description.",
            f"Add <meta name=\"description\"> of {DESCRIPTION_MIN}-{DESCRIPTION_MAX} characters.",
        ))
    elif len(description) < DESCRIPTION_MIN:
        findings.append(_finding(
            "warning", "description_too_short",
            f"Meta description is {len(description)} characters (min {DESCRIPTION_MIN}).",
            f"Expand the description to {DESCRIPTION_MIN}-{DESCRIPTION_MAX} characters.",
        ))
    elif len(description) > DESCRIPTION_MAX:
        findings.append(_finding(
            "warning", "description_too_long",
            f"Meta description is {len(description)} characters (max {DESCRIPTION_MAX}).",
            f"Trim the description to {DESCRIPTION_MAX} characters or fewer.",
        ))

    canonical_resolved = urljoin(response.final_url, parser.canonical) if parser.canonical else None
    if not canonical_resolved:
        findings.append(_finding(
            "warning", "canonical_missing", "No <link rel=\"canonical\">.",
            f"Add <link rel=\"canonical\" href=\"{response.final_url}\">.",
        ))
        canonical_self = None
    else:
        canonical_self = _norm(canonical_resolved) in {_norm(response.final_url), _norm(url)}
        if not canonical_self:
            findings.append(_finding(
                "warning", "canonical_not_self",
                f"Canonical points to {canonical_resolved}, not to this page.",
                "Point the canonical at this page's own URL unless it is deliberately a duplicate.",
            ))

    if parser.h1_count != 1:
        findings.append(_finding(
            "warning", "h1_count", f"Found {parser.h1_count} <h1> elements, expected exactly 1.",
            "Use exactly one <h1> that states the page topic.",
        ))

    meta_noindex = [
        values for values in parser.metas
        if values.get("name", "").lower() in ("robots", "googlebot", "bingbot")
        and _NOINDEX_RE.search(values.get("content", ""))
    ]
    if meta_noindex:
        findings.append(_finding(
            "critical", "noindex_meta",
            f"Meta robots contains noindex ('{meta_noindex[0].get('content', '')}').",
            "Remove 'noindex' from the meta robots tag if this page should appear in search.",
        ))

    missing_alt = sum(1 for image in parser.images if image["alt"] is None)
    if missing_alt:
        findings.append(_finding(
            "warning", "images_missing_alt", f"{missing_alt} of {len(parser.images)} images have no alt attribute.",
            "Add descriptive alt text to each image (alt=\"\" for purely decorative ones).",
        ))

    types, invalid = _jsonld_types(parser.jsonld)
    if invalid:
        findings.append(_finding(
            "warning", "jsonld_invalid", f"{invalid} JSON-LD block(s) are not valid JSON.",
            "Fix the JSON syntax in the application/ld+json script; test with the Rich Results Test.",
        ))
    if not parser.jsonld:
        findings.append(_finding(
            "info", "jsonld_missing", "No JSON-LD structured data.",
            "Add schema.org JSON-LD (e.g. Organization, WebSite or Article) where it applies.",
        ))
    og_image = parser.meta("og:image", "property")
    if not og_image:
        findings.append(_finding(
            "info", "og_image_missing", "No og:image meta tag.",
            "Add <meta property=\"og:image\"> with an absolute URL for link previews.",
        ))

    page["metrics"] = {
        "title": title,
        "title_length": len(title) if title else 0,
        "description_length": len(description) if description else 0,
        "canonical": canonical_resolved,
        "canonical_is_self": canonical_self,
        "h1_count": parser.h1_count,
        "images": len(parser.images),
        "images_missing_alt": missing_alt,
        "jsonld_blocks": len(parser.jsonld),
        "jsonld_types": types,
        "og_image": og_image or None,
    }
    return page, parser.images


def _check_image(url: str, fetch: Fetcher) -> dict[str, Any]:
    record: dict[str, Any] = {"url": url}
    try:
        response = fetch(url, "HEAD")
        if response.status >= 400 or not response.headers.get("content-length"):
            # Some servers reject HEAD or omit the length; GET answers both.
            response = fetch(url, "GET")
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record
    record.update(status=response.status, content_type=response.content_type, bytes=response.size)
    return record


# --- Entry point ---------------------------------------------------------------


def audit_site(
    url: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    sitemap_url: str | None = None,
    fetch: Fetcher | None = None,
) -> dict[str, Any]:
    """Audit a site and return summary, site findings, per-page findings and fixes."""
    parts = urlsplit(url) if isinstance(url, str) else None
    if not parts or parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("url must be an http(s) site root such as https://example.com/.")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= MAX_PAGES_CAP:
        raise ValueError(f"max_pages must be an integer between 1 and {MAX_PAGES_CAP}.")
    if sitemap_url is not None and urlsplit(sitemap_url).scheme not in ("http", "https"):
        raise ValueError("sitemap_url must be an absolute http(s) URL.")
    send = fetch or fetch_url
    root = f"{parts.scheme}://{parts.netloc}/"

    site: dict[str, Any] = {"findings": []}
    robots = _check_robots(root, send, site)
    chosen = sitemap_url
    if not chosen:
        listed = site.get("robots", {}).get("sitemaps") or []
        chosen = listed[0] if listed else root + "sitemap.xml"
    sitemap_urls = _parse_sitemap(chosen, send, site, MAX_PAGES_CAP)
    _check_redirects(root, send, site)

    # Only audit URLs on the site's own host: a sitemap must not steer the audit elsewhere.
    own = _site_host(parts.hostname or "")
    on_site = [u for u in sitemap_urls if _site_host(urlsplit(u).hostname or "") == own]
    skipped = len(sitemap_urls) - len(on_site)
    if skipped:
        site["findings"].append(_finding(
            "info", "sitemap_offsite_urls", f"{skipped} sitemap URL(s) on other hosts were not audited.",
            "Sitemaps should list only URLs on the site's own host.",
        ))
    targets = list(on_site)
    if not any(_norm(u) == _norm(root) for u in targets):
        targets.insert(0, root)
    targets = targets[:max_pages]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        audited = list(pool.map(lambda target: _audit_page(target, send), targets))
    pages = [page for page, _images in audited]

    if robots is not None:
        sitemap_set = {_norm(u) for u in on_site}
        for page in pages:
            if _norm(page["url"]) in sitemap_set and not robots.can_fetch("*", page["url"]):
                page["findings"].append(_finding(
                    "warning", "sitemap_url_disallowed",
                    "Listed in the sitemap but disallowed by robots.txt.",
                    "Either remove the URL from the sitemap or relax the matching Disallow rule.",
                ))

    # Distinct image sources across the audited pages, remembering where each was first seen.
    image_sources: dict[str, dict[str, Any]] = {}
    for page, images in audited:
        base = page.get("final_url", page["url"])
        for image in images:
            src = image["src"]
            if not src or src.startswith("data:"):
                continue
            absolute = urljoin(base, src)
            split = urlsplit(absolute)
            if split.scheme in ("http", "https") and _is_public_host(split.hostname or ""):
                image_sources.setdefault(absolute, page)
    image_urls = list(image_sources)[:MAX_IMAGES]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        images_checked = list(pool.map(lambda image_url: _check_image(image_url, send), image_urls))
    for record in images_checked:
        owner = image_sources[record["url"]]["findings"]
        if "error" in record or record["status"] >= 400:
            owner.append(_finding(
                "warning", "image_broken",
                f"Image {record['url']} failed: {record.get('error') or record['status']}.",
                "Fix or remove the broken image reference.",
            ))
        elif record["content_type"] in ("image/jpeg", "image/png") and record["bytes"] > IMAGE_WARN_BYTES:
            owner.append(_finding(
                "warning", "image_too_large",
                f"Image {record['url']} is {record['bytes'] // 1024} KB ({record['content_type']}).",
                "Convert to WebP or AVIF and compress; aim for under 100 KB.",
            ))

    fixes = []
    for url_, findings in [(root, site["findings"])] + [(p["url"], p["findings"]) for p in pages]:
        fixes.extend({"severity": f["severity"], "url": url_, **{k: f[k] for k in ("check", "detail", "suggestion")}}
                     for f in findings)
    fixes.sort(key=lambda fix: SEVERITY_ORDER[fix["severity"]])  # stable: keeps discovery order

    counts = {name: sum(1 for fix in fixes if fix["severity"] == name) for name in SEVERITY_ORDER}
    return {
        "url": root,
        "summary": {
            "pages_checked": len(pages),
            "images_checked": len(images_checked),
            "sitemap_url": site.get("sitemap", {}).get("url"),
            "sitemap_urls": site.get("sitemap", {}).get("url_count", 0),
            "by_severity": counts,
        },
        "site": site,
        "pages": pages,
        "images": images_checked,
        "fixes": fixes,
    }
