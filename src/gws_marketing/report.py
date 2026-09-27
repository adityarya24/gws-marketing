"""Weekly Search Console report as plain text, for a cron job or a chat.

    gws-marketing-report --site sc-domain:example.com \
        --inspect https://example.com/ --inspect https://example.com/pricing

Search Console data lags two to three days, so the week ends three days ago
and is compared with the seven days before it.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from typing import Any

LAG_DAYS = 3


def week_ranges(today: date) -> tuple[tuple[str, str], tuple[str, str]]:
    end = today - timedelta(days=LAG_DAYS)
    start = end - timedelta(days=6)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    return (start.isoformat(), end.isoformat()), (prev_start.isoformat(), prev_end.isoformat())


def totals(rows: list[dict[str, Any]]) -> dict[str, float]:
    clicks = sum(r.get("clicks", 0) for r in rows)
    impressions = sum(r.get("impressions", 0) for r in rows)
    # Average position weighted by impressions, the way Search Console shows it.
    weighted = sum(r.get("position", 0) * r.get("impressions", 0) for r in rows)
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": clicks / impressions if impressions else 0.0,
        "position": weighted / impressions if impressions else 0.0,
    }


def _change(now: float, before: float) -> str:
    if not before:
        return "new" if now else "-"
    pct = (now - before) / before * 100
    return f"{pct:+.0f}%"


def build_report(client: Any, site_url: str, inspect_urls: list[str], today: date | None = None) -> str:
    (start, end), (prev_start, prev_end) = week_ranges(today or date.today())
    queries = client.search_analytics(site_url, start, end, dimensions=["query"], row_limit=1000)
    prev_queries = client.search_analytics(site_url, prev_start, prev_end, dimensions=["query"], row_limit=1000)
    pages = client.search_analytics(site_url, start, end, dimensions=["page"], row_limit=10)
    # Totals come from an undimensioned query: per-query rows drop anonymised queries.
    now = totals(client.search_analytics(site_url, start, end))
    before = totals(client.search_analytics(site_url, prev_start, prev_end))

    lines = [f"Search Console: {site_url}", f"{start} to {end} (vs {prev_start} to {prev_end})", ""]
    lines.append(f"Clicks {now['clicks']:.0f} ({_change(now['clicks'], before['clicks'])})")
    lines.append(f"Impressions {now['impressions']:.0f} ({_change(now['impressions'], before['impressions'])})")
    was = f"{before['position']:.1f}" if before["impressions"] else "-"
    lines.append(f"CTR {now['ctr'] * 100:.1f}%  |  Avg position {now['position']:.1f} (was {was})")

    top = sorted(queries, key=lambda r: r.get("impressions", 0), reverse=True)[:10]
    lines += ["", "Top queries (impressions / clicks / position):"]
    lines += [f"- {r['keys'][0]}: {r['impressions']:.0f} / {r['clicks']:.0f} / {r['position']:.1f}" for r in top] or ["- none"]

    seen = {r["keys"][0] for r in prev_queries}
    fresh = [r for r in sorted(queries, key=lambda r: r.get("impressions", 0), reverse=True) if r["keys"][0] not in seen][:5]
    lines += ["", "New queries this week:"]
    lines += [f"- {r['keys'][0]} ({r['impressions']:.0f} impr, pos {r['position']:.1f})" for r in fresh] or ["- none"]

    lines += ["", "Top pages (clicks / impressions):"]
    lines += [f"- {r['keys'][0]}: {r['clicks']:.0f} / {r['impressions']:.0f}" for r in pages] or ["- none"]

    if inspect_urls:
        lines += ["", "Index status:"]
        for url in inspect_urls:
            status = client.inspect_url(site_url, url).get("indexStatusResult", {})
            crawled = (status.get("lastCrawlTime") or "never")[:10]
            lines.append(f"- {url}: {status.get('coverageState', 'unknown')} (crawled {crawled})")

    sitemaps = client.list_sitemaps(site_url)
    if sitemaps:
        lines += ["", "Sitemaps:"]
        for s in sitemaps:
            read = (s.get("lastDownloaded") or "never")[:10]
            lines.append(f"- {s['path']}: read {read}, errors {s.get('errors', 0)}, warnings {s.get('warnings', 0)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Print a weekly Search Console report.")
    parser.add_argument("--site", required=True, help="Property, e.g. sc-domain:example.com")
    parser.add_argument("--account", default="default", help="Stored credentials profile")
    parser.add_argument("--inspect", action="append", default=[], help="URL to check index status for (repeatable)")
    args = parser.parse_args(argv)

    from .server import get_client

    print(build_report(get_client("gsc_search_analytics", account=args.account), args.site, args.inspect))


if __name__ == "__main__":
    main()
