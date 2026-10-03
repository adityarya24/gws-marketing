"""Site SEO audit with a fake fetcher — no network."""
from __future__ import annotations

import pytest

from gws_marketing import seo
from gws_marketing import server as srv
from gws_marketing.seo import Response, audit_site
from gws_marketing.tools import SCHEMAS, TOOLS, handle_site_seo_audit
from tests.test_server import asyncio_run, result_payload

ROOT = "https://x.in/"
GOOD_PAGE = (
    "<html><head><title>Good page</title>"
    '<meta name="description" content="{desc}">'
    '<link rel="canonical" href="{canonical}">'
    '<meta property="og:image" content="https://x.in/og.png">'
    '<script type="application/ld+json">{{"@type": "Organization"}}</script>'
    "</head><body><h1>Hi</h1>{body}</body></html>"
)
DESC = "d" * 80
SITEMAP = (
    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "{locs}</urlset>"
)


def page(desc=DESC, canonical="https://x.in/a", body="", head_extra=""):
    return GOOD_PAGE.format(desc=desc, canonical=canonical, body=body).replace(
        "</head>", head_extra + "</head>"
    )


def sitemap(*urls):
    return SITEMAP.format(locs="".join(f"<url><loc>{u}</loc></url>" for u in urls))


class FakeWeb:
    """Maps URL -> Response or Exception; unknown URLs are an HTML 404."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, method="GET"):
        self.calls.append((method, url))
        route = self.routes.get(url)
        if isinstance(route, Exception):
            raise route
        if route is None:
            return Response(url, url, 404, {"content-type": "text/html"},
                            b"<!doctype html><title>404</title>", [url])
        if isinstance(route, str):
            route = ok(route)
        return Response(url, route.final_url or url, route.status, route.headers,
                        route.body, route.chain or [url])


def ok(body="", ctype="text/html; charset=utf-8", status=200, headers=None, chain=None, final=None):
    r = Response("", final or "", status, {"content-type": ctype, **(headers or {})},
                 body.encode() if isinstance(body, str) else body, chain or [])
    return r


def healthy_site(**overrides):
    routes = {
        ROOT + "robots.txt": ok("User-agent: *\nAllow: /\nSitemap: https://x.in/sitemap.xml\n", "text/plain"),
        ROOT + "sitemap.xml": ok(sitemap(ROOT + "a"), "application/xml"),
        ROOT: page(canonical=ROOT),
        ROOT + "a": page(),
        "http://x.in/": ok(final="https://x.in/", chain=["http://x.in/", "https://x.in/"], body="x"),
    }
    routes.update(overrides)
    return FakeWeb(routes)


def checks(result, url=None):
    return {f["check"] for f in result["fixes"] if url is None or f["url"] == url}


def test_healthy_site_has_no_critical_or_warning():
    result = audit_site(ROOT, fetch=healthy_site())
    assert result["summary"]["pages_checked"] == 2  # sitemap page plus the root added
    assert result["summary"]["sitemap_urls"] == 1
    assert result["summary"]["by_severity"]["critical"] == 0
    assert result["summary"]["by_severity"]["warning"] == 0


def test_missing_robots_with_html_404_is_flagged():
    web = healthy_site(**{ROOT + "robots.txt": ok("<!DOCTYPE html><html>Not found</html>", status=404)})
    result = audit_site(ROOT, fetch=web)
    assert result["site"]["robots"]["exists"] is False
    assert "robots_missing" in checks(result)
    # With no Sitemap line the default location is used.
    assert result["summary"]["sitemap_url"] == ROOT + "sitemap.xml"


def test_html_served_with_200_as_robots_is_also_missing():
    web = healthy_site(**{ROOT + "robots.txt": ok("<html><body>app</body></html>")})
    assert "robots_missing" in checks(audit_site(ROOT, fetch=web))


def test_disallow_all_is_critical():
    web = healthy_site(**{ROOT + "robots.txt": ok("User-agent: *\nDisallow: /\n", "text/plain")})
    result = audit_site(ROOT, fetch=web)
    assert "robots_blocks_all" in checks(result)
    assert result["fixes"][0]["severity"] == "critical"


def test_sitemap_parsing_index_and_robots_sitemap_line():
    index = ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
             "<sitemap><loc>https://x.in/s1.xml</loc></sitemap></sitemapindex>")
    web = healthy_site(**{
        ROOT + "robots.txt": ok("User-agent: *\nSitemap: https://x.in/index.xml\n", "text/plain"),
        ROOT + "index.xml": ok(index, "application/xml"),
        ROOT + "s1.xml": ok(sitemap(ROOT + "a", ROOT + "b"), "application/xml"),
        ROOT + "b": page(canonical=ROOT + "b"),
    })
    result = audit_site(ROOT, fetch=web)
    assert result["summary"]["sitemap_url"] == ROOT + "index.xml"
    assert result["summary"]["sitemap_urls"] == 2
    assert {p["url"] for p in result["pages"]} == {ROOT, ROOT + "a", ROOT + "b"}


def test_explicit_sitemap_url_and_max_pages_cap():
    urls = [f"{ROOT}p{i}" for i in range(10)]
    routes = {ROOT + "custom.xml": ok(sitemap(*urls), "application/xml")}
    routes.update({u: page(canonical=u) for u in urls})
    result = audit_site(ROOT, max_pages=3, sitemap_url=ROOT + "custom.xml", fetch=FakeWeb(routes))
    assert result["summary"]["pages_checked"] == 3
    assert result["summary"]["sitemap_urls"] == 10


def test_invalid_sitemap_is_a_finding():
    web = healthy_site(**{ROOT + "sitemap.xml": ok("<urlset><url>", "application/xml")})
    assert "sitemap_invalid" in checks(audit_site(ROOT, fetch=web))


def test_noindex_in_meta_and_header_is_critical():
    web = healthy_site(**{
        ROOT + "a": page(head_extra='<meta name="robots" content="index, NoIndex">'),
        ROOT: ok(page(canonical=ROOT), headers={"x-robots-tag": "noindex, nofollow"}),
    })
    result = audit_site(ROOT, fetch=web)
    assert "noindex_meta" in checks(result, ROOT + "a")
    assert "noindex_header" in checks(result, ROOT)
    assert {f["severity"] for f in result["fixes"] if f["check"].startswith("noindex")} == {"critical"}


def test_hindi_description_counts_characters_not_bytes():
    hindi = "नमस्ते " * 10  # 69 characters, 189 bytes
    assert len(hindi.strip().encode()) > 160 and len(hindi.strip()) == 69
    web = healthy_site(**{ROOT + "a": page(desc=hindi)})
    result = audit_site(ROOT, fetch=web)
    record = next(p for p in result["pages"] if p["url"] == ROOT + "a")
    assert record["metrics"]["description_length"] == 69
    assert "description_too_long" not in checks(result)
    assert "description_too_short" not in checks(result)


def test_description_length_limits_and_entities():
    short = healthy_site(**{ROOT + "a": page(desc="too short")})
    assert "description_too_short" in checks(audit_site(ROOT, fetch=short))
    long_ = healthy_site(**{ROOT + "a": page(desc="x" * 161)})
    assert "description_too_long" in checks(audit_site(ROOT, fetch=long_))
    # &amp; is one character once unescaped.
    entity = healthy_site(**{ROOT + "a": page(desc="a&amp;b" * 20)})
    record = next(p for p in audit_site(ROOT, fetch=entity)["pages"] if p["url"] == ROOT + "a")
    assert record["metrics"]["description_length"] == 60


def test_canonical_trailing_slash_counts_as_self():
    web = healthy_site(**{ROOT + "a": page(canonical="https://x.in/a/")})
    result = audit_site(ROOT, fetch=web)
    assert "canonical_not_self" not in checks(result)
    other = healthy_site(**{ROOT + "a": page(canonical="https://x.in/other")})
    assert "canonical_not_self" in checks(audit_site(ROOT, fetch=other))


def test_title_h1_alt_and_jsonld_checks():
    html = (
        "<html><head><title>" + "T" * 61 + "</title></head><body><h1>a</h1><h1>b</h1>"
        '<img src="/i.png"><img src="/j.png" alt=""><script type="application/ld+json">{bad</script>'
        "</body></html>"
    )
    result = audit_site(ROOT, fetch=healthy_site(**{ROOT + "a": html}))
    found = checks(result, ROOT + "a")
    assert {"title_too_long", "h1_count", "images_missing_alt", "jsonld_invalid",
            "description_missing", "canonical_missing", "og_image_missing"} <= found


def test_jsonld_types_are_listed():
    html = page(head_extra='<script type="application/ld+json">{"@graph":[{"@type":["Person","Thing"]}]}</script>')
    result = audit_site(ROOT, fetch=healthy_site(**{ROOT + "a": html}))
    record = next(p for p in result["pages"] if p["url"] == ROOT + "a")
    assert record["metrics"]["jsonld_types"] == ["Organization", "Person", "Thing"]


def test_redirect_chain_of_two_hops_is_flagged_at_site_and_page_level():
    chain = ["http://www.x.in/", "https://www.x.in/", "https://x.in/"]
    web = healthy_site(**{
        "http://www.x.in/": ok("x", final="https://x.in/", chain=chain),
        ROOT + "a": ok(page(), final=ROOT + "a", chain=["https://x.in/old", "https://x.in/mid", ROOT + "a"]),
    })
    result = audit_site(ROOT, fetch=web)
    site_chain = [f for f in result["fixes"] if f["check"] == "redirect_chain" and f["url"] == ROOT]
    assert len(site_chain) == 1 and "http://www.x.in/" in site_chain[0]["detail"]
    assert "redirect_chain" in checks(result, ROOT + "a")


def test_one_failing_page_does_not_kill_the_audit():
    web = healthy_site(**{
        ROOT + "sitemap.xml": ok(sitemap(ROOT + "a", ROOT + "boom", ROOT + "gone"), "application/xml"),
        ROOT + "boom": TimeoutError("timed out"),
    })
    result = audit_site(ROOT, fetch=web)
    assert result["summary"]["pages_checked"] == 4
    assert "fetch_failed" in checks(result, ROOT + "boom")
    assert "status_code" in checks(result, ROOT + "gone")  # the HTML 404
    assert "title_missing" not in checks(result, ROOT + "a")


def test_large_jpeg_flagged_but_small_or_webp_not():
    body = '<img src="/big.jpg" alt="a"><img src="/small.jpg" alt="a"><img src="/big.webp" alt="a">'
    sizes = {"big.jpg": ("image/jpeg", "180000"), "small.jpg": ("image/jpeg", "20000"),
             "big.webp": ("image/webp", "500000")}
    routes = {ROOT + "a": page(body=body)}
    for name, (ctype, length) in sizes.items():
        routes[ROOT + name] = ok(b"", ctype, headers={"content-length": length})
    result = audit_site(ROOT, fetch=healthy_site(**routes))
    flagged = [f for f in result["fixes"] if f["check"] == "image_too_large"]
    assert len(flagged) == 1 and "big.jpg" in flagged[0]["detail"] and "WebP" in flagged[0]["suggestion"]
    assert result["summary"]["images_checked"] == 3


def test_image_check_is_capped_and_skips_private_hosts():
    body = "".join(f'<img src="/i{n}.png" alt="a">' for n in range(40))
    body += '<img src="http://127.0.0.1/x.png" alt="a"><img src="data:image/png;base64,AA" alt="a">'
    web = healthy_site(**{ROOT + "a": page(body=body)})
    result = audit_site(ROOT, fetch=web)
    assert result["summary"]["images_checked"] == seo.MAX_IMAGES
    assert not any("127.0.0.1" in url for _m, url in web.calls)


def test_sitemap_url_disallowed_by_robots_is_flagged():
    web = healthy_site(**{
        ROOT + "robots.txt": ok("User-agent: *\nDisallow: /a\n", "text/plain"),
    })
    assert "sitemap_url_disallowed" in checks(audit_site(ROOT, fetch=web), ROOT + "a")


def test_offsite_sitemap_urls_are_not_fetched():
    web = healthy_site(**{
        ROOT + "sitemap.xml": ok(sitemap(ROOT + "a", "http://169.254.169.254/latest"), "application/xml"),
    })
    result = audit_site(ROOT, fetch=web)
    assert "sitemap_offsite_urls" in checks(result)
    assert not any("169.254" in url for _m, url in web.calls)


def test_fixes_are_sorted_by_severity_and_carry_all_fields():
    web = healthy_site(**{ROOT + "a": page(desc="short", head_extra='<meta name="robots" content="noindex">')})
    fixes = audit_site(ROOT, fetch=web)["fixes"]
    order = [seo.SEVERITY_ORDER[f["severity"]] for f in fixes]
    assert order == sorted(order) and fixes[0]["severity"] == "critical"
    assert all(set(f) == {"severity", "url", "check", "detail", "suggestion"} for f in fixes)


@pytest.mark.parametrize("kwargs", [
    {"url": "example.com"}, {"url": "ftp://x.in/"}, {"url": ROOT, "max_pages": 0},
    {"url": ROOT, "max_pages": 201}, {"url": ROOT, "sitemap_url": "nope"},
])
def test_bad_arguments_raise_value_error(kwargs):
    with pytest.raises(ValueError):
        audit_site(fetch=healthy_site(), **kwargs)


def test_registry_and_handler_wiring():
    assert TOOLS["site_seo_audit"] is handle_site_seo_audit
    assert SCHEMAS["site_seo_audit"]["required"] == ["url"]
    assert "account" not in SCHEMAS["site_seo_audit"]["properties"]
    from gws_marketing.gsc import group_for_tool
    assert group_for_tool("site_seo_audit") is None


def test_handle_call_needs_no_google_client(monkeypatch):
    def no_client(*_a, **_k):
        raise AssertionError("site_ tools must not resolve a Google client")

    monkeypatch.setattr(srv, "get_client", no_client)
    monkeypatch.setattr(seo, "fetch_url", healthy_site())
    result = asyncio_run(srv.handle_call("site_seo_audit", {"url": ROOT, "max_pages": 5}))
    assert result.isError is False
    assert result_payload(result)["summary"]["pages_checked"] >= 1
    bad = asyncio_run(srv.handle_call("site_seo_audit", {"url": "nope"}))
    assert bad.isError is True and result_payload(bad)["type"] == "validation_error"
