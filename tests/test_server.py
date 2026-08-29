"""Server wiring tests: registry exposure and dispatch without credentials."""
from __future__ import annotations

import json

import pytest

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


def test_handle_call_unknown_tool_returns_error_json():
    result = asyncio_run(srv.handle_call("nope", {}))
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["type"] == "unknown_tool"
    assert "nope" in payload["error"]


def test_handle_call_returns_validation_error_json(monkeypatch):
    from tests.test_tools import FakeGscClient

    monkeypatch.setattr(srv, "get_client", lambda name, account="default": FakeGscClient())
    result = asyncio_run(
        srv.handle_call(
            "gsc_search_analytics",
            {"site_url": "x", "start_date": "bad", "end_date": "2026-08-23"},
        )
    )
    payload = json.loads(result[0].text)
    assert payload["type"] == "validation_error"
    assert payload["tool"] == "gsc_search_analytics"


def test_handle_call_returns_runtime_error_json(monkeypatch):
    monkeypatch.setattr(srv, "load_credentials", lambda account="default": None)
    result = asyncio_run(srv.handle_call("gsc_list_sites", {}))
    payload = json.loads(result[0].text)
    assert payload["type"] == "runtime_error"
    assert "No stored Google credentials" in payload["error"]


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


def test_get_client_refuses_a_tool_whose_group_was_not_granted(monkeypatch):
    """A narrow token must fail here, with an actionable message.

    Without this gate the call reaches Google and comes back as an opaque 403,
    which tells the user nothing about what to do next.
    """
    monkeypatch.setattr(srv, "load_credentials", lambda account="default": object())
    monkeypatch.setattr(srv, "granted_groups", lambda account="default": ["search"])

    with pytest.raises(RuntimeError, match="has not granted the 'gmail' scope group"):
        srv.get_client("gmail_search_messages")


def test_get_client_allows_a_tool_whose_group_was_granted(monkeypatch):
    monkeypatch.setattr(srv, "load_credentials", lambda account="default": object())
    monkeypatch.setattr(srv, "granted_groups", lambda account="default": ["search"])
    monkeypatch.setattr(
        srv, "build_client", lambda credentials: "gsc-client"
    )

    assert srv.get_client("gsc_list_sites") == "gsc-client"


def test_missing_required_argument_returns_a_validation_error(monkeypatch):
    """A missing required arg must not escape handle_call.

    Every other failure mode already comes back as a JSON tool error; a
    KeyError from ``kwargs["site_url"]`` used to propagate instead.
    """
    monkeypatch.setattr(srv, "get_client", lambda name, account="default": object())

    result = asyncio_run(srv.handle_call("gsc_list_sitemaps", {}))
    payload = json.loads(result[0].text)

    assert payload["type"] == "validation_error"
    assert "site_url" in payload["error"]


def test_unexpected_exceptions_come_back_as_tool_errors(monkeypatch):
    """A client blowing up (network, JSON, anything) is still a tool error."""

    def explode(*_args, **_kwargs):
        raise ConnectionError("connection reset by peer")

    monkeypatch.setattr(srv, "get_client", lambda name, account="default": object())
    monkeypatch.setitem(srv.TOOLS, "gsc_list_sites", explode)

    result = asyncio_run(srv.handle_call("gsc_list_sites", {}))
    payload = json.loads(result[0].text)

    assert payload["type"] == "unexpected_error"
    assert "ConnectionError" in payload["error"]


def test_get_client_refuses_a_tool_family_it_has_no_client_for(monkeypatch):
    """An unregistered prefix must raise, not quietly return the GA4 client."""
    monkeypatch.setattr(srv, "load_credentials", lambda account="default": object())
    monkeypatch.setattr(srv, "granted_groups", lambda account="default": ["search"])

    with pytest.raises(RuntimeError, match="No client is registered"):
        srv.get_client("sheets_read_range")
