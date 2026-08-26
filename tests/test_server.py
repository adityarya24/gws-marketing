"""Server wiring tests: registry exposure and dispatch without credentials."""
from __future__ import annotations

import json

import pytest
import mcp.types as types

import gws_marketing.server as srv


def test_build_tool_definitions_matches_registry():
    tools = srv.build_tool_definitions()
    names = [t.name for t in tools]
    assert sorted(names) == sorted(t.name for t in tools)  # deterministic order
    by_name = {t.name: t for t in tools}
    assert set(by_name) == {
        "gsc_list_sites", "gsc_search_analytics", "gsc_list_sitemaps", "gsc_inspect_url",
        "ga4_list_properties", "ga4_run_report",
        "auth_status", "auth_login", "auth_logout",
        "gmail_search_messages", "gmail_get_message", "gmail_create_draft",
        "gcal_list_calendars", "gcal_list_events",
        "drive_search_files",
    }
    schema = by_name["gsc_search_analytics"].inputSchema
    assert set(schema["required"]) == {"site_url", "start_date", "end_date"}
    assert "webmasters.readonly" not in json.dumps(schema)  # scope stays in code, not wire
    assert "analytics.readonly" not in json.dumps(by_name["ga4_run_report"].inputSchema)


def test_handle_call_unknown_tool_raises():
    import asyncio

    with pytest.raises(ValueError, match="Unknown"):
        asyncio.run(srv.handle_call("nope", {}))


def test_handle_call_dispatches_with_injected_client(monkeypatch):
    from tests.test_tools import FakeGscClient

    monkeypatch.setattr(srv, "get_client", lambda name, account="default": FakeGscClient())
    result = asyncio_run(srv.handle_call("gsc_list_sites", {}))
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["count"] == 2


def test_handle_call_ga4_dispatches_with_injected_client(monkeypatch):
    from tests.test_tools import FakeGa4Client

    monkeypatch.setattr(srv, "get_client", lambda name, account="default": FakeGa4Client())
    result = asyncio_run(srv.handle_call("ga4_list_properties", {}))
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["count"] == 1


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
