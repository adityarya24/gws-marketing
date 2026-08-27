"""Registry behaviour tests with fake clients — no network, no Google libs."""
from __future__ import annotations

import pytest

from gws_marketing.tools import (
    DESCRIPTIONS,
    SCHEMAS,
    TOOLS,
    handle_auth_login,
    handle_auth_logout,
    handle_auth_status,
    handle_drive_search_files,
    handle_ga4_list_properties,
    handle_ga4_run_report,
    handle_gcal_list_calendars,
    handle_gcal_list_events,
    handle_gmail_create_draft,
    handle_gmail_get_message,
    handle_gmail_search_messages,
    handle_inspect_url,
    handle_list_sitemaps,
    handle_list_sites,
    handle_search_analytics,
)


class FakeGscClient:
    def list_sites(self):
        return [
            {"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"},
            {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"},
        ]

    def search_analytics(self, site_url, start_date, end_date, dimensions=None,
                         query=None, row_limit=100, start_row=0):
        assert site_url == "sc-domain:example.com"
        assert start_date == "2026-08-01" and end_date == "2026-08-23"
        return [
            {"keys": ["kundli milan"], "clicks": 12, "impressions": 340,
             "ctr": 0.0353, "position": 18.4},
        ] * 2

    def list_sitemaps(self, site_url):
        return [{"path": "sitemap.xml", "type": "sitemap", "isPending": False}]

    def inspect_url(self, site_url, inspection_url):
        return {
            "indexStatusResult": {"verdict": "NEUTRAL", "coverageState":
                                  "Crawled - currently not indexed"},
        }


def test_registry_integrity():
    assert set(TOOLS) == set(SCHEMAS) == set(DESCRIPTIONS)
    assert all(
        name.startswith(("gsc_", "ga4_", "auth_", "gmail_", "gcal_", "drive_"))
        for name in TOOLS
    )


def test_list_sites_shape():
    out = handle_list_sites(FakeGscClient())
    assert out["count"] == 2
    assert any(s["permissionLevel"] == "siteOwner" for s in out["sites"])


def test_search_analytics_passes_arguments():
    out = handle_search_analytics(
        FakeGscClient(),
        site_url="sc-domain:example.com",
        start_date="2026-08-01",
        end_date="2026-08-23",
        dimensions=["query"],
        row_limit=10,
    )
    assert out["count"] == 2
    assert out["rows"][0]["keys"] == ["kundli milan"]
    assert out["dimensions"] == ["query"]


def test_search_analytics_rejects_bad_dimension():
    with pytest.raises(ValueError, match="Invalid dimensions"):
        handle_search_analytics(
            FakeGscClient(),
            site_url="x",
            start_date="2026-08-01",
            end_date="2026-08-23",
            dimensions=["bogus"],
        )


@pytest.mark.parametrize("bad", ["20260801", "2026-8-01", "not-a-date"])
def test_search_analytics_rejects_bad_dates(bad):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        handle_search_analytics(
            FakeGscClient(),
            site_url="x",
            start_date=bad,
            end_date="2026-08-23",
        )


def test_row_limit_bounds():
    with pytest.raises(ValueError, match="row_limit"):
        handle_search_analytics(
            FakeGscClient(),
            site_url="x",
            start_date="2026-08-01",
            end_date="2026-08-23",
            row_limit=0,
        )
    with pytest.raises(ValueError, match="row_limit"):
        handle_search_analytics(
            FakeGscClient(),
            site_url="x",
            start_date="2026-08-01",
            end_date="2026-08-23",
            row_limit=999999,
        )


def test_list_sitemaps_and_inspect():
    sitemaps = handle_list_sitemaps(FakeGscClient(), site_url="https://example.com/")
    assert sitemaps["count"] == 1

    inspected = handle_inspect_url(
        FakeGscClient(),
        site_url="sc-domain:example.com",
        inspection_url="https://example.com/free-calculators",
    )
    assert inspected["verdict"] == "NEUTRAL"


class FakeGa4Client:
    def list_properties(self):
        return [
            {
                "account": "Example Business",
                "property": "example.com",
                "property_id": "482617935",
            }
        ]

    def run_report(self, property_id, start_date, end_date, dimensions=None,
                   metrics=None, row_limit=100, offset=0):
        assert property_id == "482617935"
        assert metrics == ["activeUsers"]
        return {
            "row_count": 1,
            "rows": [{"keys": ["India"], "values": ["57"]}],
        }


def test_ga4_registry_names():
    assert {"ga4_list_properties", "ga4_run_report"} <= set(TOOLS)


def test_ga4_list_properties_shape():
    out = handle_ga4_list_properties(FakeGa4Client())
    assert out["count"] == 1
    assert out["properties"][0]["property_id"] == "482617935"


def test_ga4_run_report_passes_arguments():
    out = handle_ga4_run_report(
        FakeGa4Client(),
        property_id="482617935",
        start_date="7daysAgo",
        end_date="today",
        dimensions=["country"],
        metrics=["activeUsers"],
        row_limit=10,
    )
    assert out["row_count"] == 1
    assert out["rows"][0]["values"] == ["57"]
    assert out["dimensions"] == ["country"]


@pytest.mark.parametrize("bad", ["20260801", "2026-8-01", "tomorrow", "daysAgo"])
def test_ga4_run_report_rejects_bad_dates(bad):
    with pytest.raises(ValueError, match="start_date"):
        handle_ga4_run_report(
            FakeGa4Client(),
            property_id="123",
            start_date=bad,
            end_date="today",
            metrics=["activeUsers"],
        )


def test_ga4_run_report_rejects_bad_property_and_idents():
    with pytest.raises(ValueError, match="property_id"):
        handle_ga4_run_report(
            FakeGa4Client(), property_id="abc", start_date="today",
            end_date="today", metrics=["activeUsers"],
        )
    with pytest.raises(ValueError, match="dimensions"):
        handle_ga4_run_report(
            FakeGa4Client(), property_id="123", start_date="today",
            end_date="today", dimensions=["bad-dim!"], metrics=["activeUsers"],
        )


def test_ga4_run_report_requires_metric_and_bounds_row_limit():
    with pytest.raises(ValueError, match="metric"):
        handle_ga4_run_report(
            FakeGa4Client(), property_id="123", start_date="today", end_date="today",
        )
    with pytest.raises(ValueError, match="row_limit"):
        handle_ga4_run_report(
            FakeGa4Client(), property_id="123", start_date="today",
            end_date="today", metrics=["activeUsers"], row_limit=0,
        )
    with pytest.raises(ValueError, match="row_limit"):
        handle_ga4_run_report(
            FakeGa4Client(), property_id="123", start_date="today",
            end_date="today", metrics=["activeUsers"], row_limit=999999,
        )


def test_auth_status_lists_profiles(monkeypatch):
    from gws_marketing import auth

    monkeypatch.setattr(
        auth, "list_profiles",
        lambda: [{"account": "default", "scopes": ["s1"], "has_refresh_token": True}],
    )
    out = handle_auth_status(None)
    assert out["count"] == 1
    assert out["profiles"][0]["account"] == "default"


def test_auth_login_passes_profile(monkeypatch):
    from gws_marketing import auth

    seen = {}

    def fake_login(profile, groups=None):
        seen["profile"] = profile
        seen["groups"] = groups
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr(auth, "login", fake_login)
    out = handle_auth_login(None, account="support")
    assert seen["profile"] == "support"
    assert out["account"] == "support"
    assert out["status"] == "ok"


def test_auth_login_defaults_exclude_restricted_scopes(monkeypatch):
    """The default consent must not reach into Gmail or Drive.

    This is the whole point of grouping scopes: someone reading Search Console
    numbers should never be asked to hand over their mailbox.
    """
    from gws_marketing import auth

    seen = {}

    def fake_login(profile, groups=None):
        seen["groups"] = groups
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr(auth, "login", fake_login)
    monkeypatch.delenv("GWS_SCOPES", raising=False)
    out = handle_auth_login(None)

    assert seen["groups"] is None  # auth.login applies the default itself
    assert out["groups"] == ["search", "analytics"]
    assert "gmail" not in out["groups"] and "drive" not in out["groups"]


def test_auth_login_forwards_requested_groups(monkeypatch):
    from gws_marketing import auth

    seen = {}

    def fake_login(profile, groups=None):
        seen["groups"] = groups
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr(auth, "login", fake_login)
    out = handle_auth_login(None, scopes=["search", "gmail"])
    assert seen["groups"] == ["search", "gmail"]
    assert out["groups"] == ["search", "gmail"]


def test_auth_login_rejects_non_list_scopes(monkeypatch):
    from gws_marketing import auth

    monkeypatch.setattr(
        auth,
        "login",
        lambda profile, groups=None: {"ok": True, "message": "ok"},
    )
    with pytest.raises(ValueError, match="scopes must be a list"):
        handle_auth_login(None, scopes="gmail")

    default_out = handle_auth_login(None)
    assert default_out["account"] == "default"
    assert default_out["status"] == "ok"


def test_auth_login_reports_error_when_client_secret_missing(monkeypatch):
    from gws_marketing import auth

    monkeypatch.setattr(
        auth,
        "login",
        lambda profile, groups=None: {
            "ok": False,
            "message": "No OAuth client secret found.",
        },
    )
    out = handle_auth_login(None)
    assert out["status"] == "error"
    assert "client secret" in out["message"]


def test_auth_logout_passes_profile(monkeypatch):
    from gws_marketing import auth

    monkeypatch.setattr(auth, "logout", lambda profile: f"removed {profile}")
    out = handle_auth_logout(None, account="stale")
    assert "stale" in out["message"]


class FakeGmailClient:
    def search_messages(self, query=None, max_results=10):
        assert max_results == 5 and query == "is:unread"
        return [{"id": "m1", "subject": "Hi", "from": "x@y.z"}]

    def get_message(self, message_id):
        return {"id": message_id, "snippet": "body"}

    def create_draft(self, to, subject, body):
        assert to == "a@b.co" and subject and body
        return {"draft_id": "d1", "to": to}


class FakeGcalClient:
    def list_calendars(self):
        return [{"id": "primary", "summary": "Main"}]

    def list_events(self, calendar_id="primary", time_min=None, time_max=None,
                    query=None, max_results=10):
        assert calendar_id == "primary"
        return [{"summary": "Standup"}]


class FakeDriveClient:
    def search_files(self, query=None, max_results=20):
        assert max_results == 3
        return [{"id": "f1", "name": "Report.pdf"}]


def test_gmail_search_and_get():
    out = handle_gmail_search_messages(FakeGmailClient(), query="is:unread", max_results=5)
    assert out["count"] == 1
    got = handle_gmail_get_message(FakeGmailClient(), message_id="m1")
    assert got["message"]["snippet"] == "body"


@pytest.mark.parametrize("bad_max", [0, 26])
def test_gmail_search_rejects_bad_max(bad_max):
    with pytest.raises(ValueError, match="max_results"):
        handle_gmail_search_messages(FakeGmailClient(), max_results=bad_max)


def test_gmail_create_draft_validates_and_flags_not_sent():
    out = handle_gmail_create_draft(
        FakeGmailClient(), to="a@b.co", subject="Namaste", body="Report attached."
    )
    assert out["draft_id"] == "d1"
    assert "NOT sent" in out["note"]
    with pytest.raises(ValueError, match="recipient email"):
        handle_gmail_create_draft(FakeGmailClient(), to="not-an-email",
                                  subject="s", body="b")
    with pytest.raises(ValueError, match="body"):
        handle_gmail_create_draft(FakeGmailClient(), to="a@b.co", subject="s", body="   ")


def test_gcal_calendars_and_events_validation():
    cals = handle_gcal_list_calendars(FakeGcalClient())
    assert cals["count"] == 1

    events = handle_gcal_list_events(
        FakeGcalClient(), time_min="2026-08-26T00:00:00+05:30", time_max="2026-08-27"
    )
    assert events["count"] == 1
    with pytest.raises(ValueError, match="time_min"):
        handle_gcal_list_events(FakeGcalClient(), time_min="tomorrow")
    with pytest.raises(ValueError, match="max_results"):
        handle_gcal_list_events(FakeGcalClient(), max_results=99)


def test_drive_search_bounds():
    out = handle_drive_search_files(FakeDriveClient(), query="report", max_results=3)
    assert out["files"][0]["name"] == "Report.pdf"
    with pytest.raises(ValueError, match="max_results"):
        handle_drive_search_files(FakeDriveClient(), max_results=0)


def test_drive_escape_query_literals():
    from gws_marketing.drive import _escape_drive_query_literal

    assert _escape_drive_query_literal("O'Brien") == "O\\'Brien"
    assert _escape_drive_query_literal(r"a\b") == r"a\\b"


def test_resolve_scopes_defaults_and_rejects_unknown():
    from gws_marketing.gsc import (
        DEFAULT_SCOPE_GROUPS,
        RESTRICTED_GROUPS,
        resolve_scopes,
    )

    default = resolve_scopes()
    assert default == [
        "https://www.googleapis.com/auth/webmasters.readonly",
        "https://www.googleapis.com/auth/analytics.readonly",
    ]
    assert not any("gmail" in scope or "drive" in scope for scope in default)
    assert RESTRICTED_GROUPS == {"gmail", "drive"}
    assert DEFAULT_SCOPE_GROUPS == ("search", "analytics")

    with pytest.raises(ValueError, match="Unknown scope group"):
        resolve_scopes(["search", "nope"])


def test_groups_for_scopes_reports_only_complete_groups():
    from gws_marketing.gsc import groups_for_scopes

    # gmail needs both readonly and compose; one alone does not grant the group.
    partial = groups_for_scopes(["https://www.googleapis.com/auth/gmail.readonly"])
    assert "gmail" not in partial

    full = groups_for_scopes(
        [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
        ]
    )
    assert full == ["gmail"]


def test_group_for_tool_maps_every_tool_family():
    from gws_marketing.gsc import group_for_tool

    assert group_for_tool("gsc_list_sites") == "search"
    assert group_for_tool("ga4_run_report") == "analytics"
    assert group_for_tool("gmail_create_draft") == "gmail"
    assert group_for_tool("gcal_list_events") == "calendar"
    assert group_for_tool("drive_search_files") == "drive"
    assert group_for_tool("auth_status") is None
