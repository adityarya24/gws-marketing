from datetime import date

from gws_marketing.report import build_report, totals, week_ranges


def test_week_ranges_skip_the_reporting_lag():
    (start, end), (prev_start, prev_end) = week_ranges(date(2026, 9, 27))
    assert (start, end) == ("2026-09-18", "2026-09-24")
    assert (prev_start, prev_end) == ("2026-09-11", "2026-09-17")


def test_totals_weight_position_by_impressions():
    out = totals([
        {"clicks": 1, "impressions": 10, "position": 2.0},
        {"clicks": 0, "impressions": 30, "position": 10.0},
    ])
    assert out["clicks"] == 1 and out["impressions"] == 40
    assert out["position"] == 8.0


class FakeClient:
    def search_analytics(self, site_url, start_date, end_date, dimensions=None, row_limit=100):
        this_week = start_date == "2026-09-18"
        if dimensions == ["query"]:
            rows = [{"keys": ["janma patrika"], "clicks": 2, "impressions": 50, "position": 6.0}]
            if this_week:
                rows.append({"keys": ["free kundli hindi"], "clicks": 0, "impressions": 20, "position": 14.0})
            return rows
        if dimensions == ["page"]:
            return [{"keys": ["https://example.com/"], "clicks": 2, "impressions": 70, "position": 8.0}]
        return [{"clicks": 2 if this_week else 1, "impressions": 70 if this_week else 50, "position": 8.0}]

    def inspect_url(self, site_url, url):
        return {"indexStatusResult": {"coverageState": "Submitted and indexed", "lastCrawlTime": "2026-09-26T10:00:00Z"}}

    def list_sitemaps(self, site_url):
        return [{"path": "https://example.com/sitemap.xml", "lastDownloaded": "2026-09-26T00:00:00Z", "errors": 0, "warnings": 0}]


def test_report_flags_new_queries_and_index_status():
    text = build_report(FakeClient(), "sc-domain:example.com", ["https://example.com/"], today=date(2026, 9, 27))
    assert "Clicks 2 (+100%)" in text
    assert "- free kundli hindi (20 impr, pos 14.0)" in text
    new_section = text.split("New queries this week:")[1].split("Top pages")[0]
    assert "janma patrika" not in new_section
    assert "https://example.com/: Submitted and indexed (crawled 2026-09-26)" in text
    assert "sitemap.xml: read 2026-09-26, errors 0" in text
