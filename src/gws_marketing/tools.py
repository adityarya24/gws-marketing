"""Tool registry: the single source of truth for gws-marketing MCP tools.

Every handler takes a client object as its first argument (GSC handlers a
:class:`gws_marketing.gsc.GscRestClient`, GA4 handlers a
:class:`gws_marketing.ga4.Ga4RestClient`) so tests can inject fakes; the
server resolves the right real client lazily from the tool-name prefix.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .ga4 import MAX_DIMENSIONS as GA4_MAX_DIMENSIONS
from .ga4 import MAX_METRICS as GA4_MAX_METRICS
from .ga4 import MAX_ROW_LIMIT as GA4_MAX_ROW_LIMIT
from .gsc import MAX_ROW_LIMIT

VALID_DIMENSIONS = {"date", "query", "page", "device", "country"}

_GA4_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_GA4_RELATIVE_RE = re.compile(r"^\d+daysAgo$")
_GA4_IDENT_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


# --- Handlers ----------------------------------------------------------------


def handle_list_sites(client: Any, **_kwargs: Any) -> dict[str, Any]:
    sites = client.list_sites()
    return {
        "sites": sites,
        "count": len(sites),
    }


def _validate_dates(start_date: str, end_date: str) -> None:
    for value in (start_date, end_date):
        if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
            raise ValueError("Dates must be YYYY-MM-DD strings.")


def handle_search_analytics(client: Any, **kwargs: Any) -> dict[str, Any]:
    site_url = kwargs["site_url"]
    start_date = kwargs["start_date"]
    end_date = kwargs["end_date"]
    _validate_dates(start_date, end_date)

    dimensions = kwargs.get("dimensions") or []
    invalid = sorted(set(dimensions) - VALID_DIMENSIONS)
    if invalid:
        raise ValueError(f"Invalid dimensions: {invalid}. Valid: {sorted(VALID_DIMENSIONS)}")

    row_limit = int(kwargs.get("row_limit", 100))
    if not 1 <= row_limit <= MAX_ROW_LIMIT:
        raise ValueError(f"row_limit must be between 1 and {MAX_ROW_LIMIT}.")

    rows = client.search_analytics(
        site_url=site_url,
        start_date=start_date,
        end_date=end_date,
        dimensions=list(dimensions),
        query=kwargs.get("query"),
        row_limit=row_limit,
        start_row=int(kwargs.get("start_row", 0)),
    )
    return {
        "site_url": site_url,
        "start_date": start_date,
        "end_date": end_date,
        "dimensions": list(dimensions),
        "rows": rows,
        "count": len(rows),
    }


def handle_list_sitemaps(client: Any, **kwargs: Any) -> dict[str, Any]:
    site_url = kwargs["site_url"]
    sitemaps = client.list_sitemaps(site_url=site_url)
    return {"site_url": site_url, "sitemaps": sitemaps, "count": len(sitemaps)}


def handle_inspect_url(client: Any, **kwargs: Any) -> dict[str, Any]:
    result = client.inspect_url(
        site_url=kwargs["site_url"],
        inspection_url=kwargs["inspection_url"],
    )
    verdict = result.get("indexStatusResult", {}).get("verdict")
    return {"inspection_result": result, "verdict": verdict}


# --- GA4 handlers ---------------------------------------------------------------


def _validate_ga4_date(value: str, label: str) -> None:
    if (
        isinstance(value, str)
        and (_GA4_DATE_RE.match(value)
             or value in ("today", "yesterday")
             or _GA4_RELATIVE_RE.match(value))
    ):
        return
    raise ValueError(
        f"{label} must be YYYY-MM-DD, 'today', 'yesterday', or '<N>daysAgo'."
    )


def _validate_ga4_idents(values: list[str], label: str, max_count: int) -> list[str]:
    if len(values) > max_count:
        raise ValueError(f"At most {max_count} {label} allowed.")
    invalid = sorted(v for v in values if not _GA4_IDENT_RE.match(v))
    if invalid:
        raise ValueError(f"Invalid {label} identifiers: {invalid}")
    return list(values)


def handle_ga4_list_properties(client: Any, **_kwargs: Any) -> dict[str, Any]:
    properties = client.list_properties()
    return {"properties": properties, "count": len(properties)}


def handle_ga4_run_report(client: Any, **kwargs: Any) -> dict[str, Any]:
    property_id = str(kwargs["property_id"]).strip()
    if not property_id.isdigit():
        raise ValueError("property_id must be the numeric GA4 property ID.")

    start_date = kwargs["start_date"]
    end_date = kwargs["end_date"]
    _validate_ga4_date(start_date, "start_date")
    _validate_ga4_date(end_date, "end_date")

    dimensions = _validate_ga4_idents(
        [str(d) for d in (kwargs.get("dimensions") or [])],
        "dimensions",
        GA4_MAX_DIMENSIONS,
    )
    metrics = _validate_ga4_idents(
        [str(m) for m in (kwargs.get("metrics") or [])],
        "metrics",
        GA4_MAX_METRICS,
    )
    if not metrics:
        raise ValueError("At least one metric is required (e.g. activeUsers).")

    row_limit = int(kwargs.get("row_limit", 100))
    if not 1 <= row_limit <= GA4_MAX_ROW_LIMIT:
        raise ValueError(f"row_limit must be between 1 and {GA4_MAX_ROW_LIMIT}.")
    offset = int(kwargs.get("offset", 0))
    if offset < 0:
        raise ValueError("offset must be >= 0.")

    result = client.run_report(
        property_id=property_id,
        start_date=start_date,
        end_date=end_date,
        dimensions=dimensions,
        metrics=metrics,
        row_limit=row_limit,
        offset=offset,
    )
    return {
        "property_id": property_id,
        "start_date": start_date,
        "end_date": end_date,
        "dimensions": dimensions,
        "metrics": metrics,
        "row_count": result.get("row_count", 0),
        "rows": result.get("rows", []),
    }


# --- Auth handlers (client is unused; flows talk to local token storage) ----


def handle_auth_status(_client: Any, **_kwargs: Any) -> dict[str, Any]:
    from . import auth
    from .gsc import SCOPE_GROUPS, groups_for_scopes

    profiles = auth.list_profiles()
    # Say which groups each profile actually holds, so a caller can see why a
    # tool is refusing before it refuses.
    for profile in profiles:
        profile["groups"] = groups_for_scopes(profile.get("scopes"))
    return {
        "profiles": profiles,
        "count": len(profiles),
        "available_groups": sorted(SCOPE_GROUPS),
        "default_groups": auth.default_groups(),
    }


def handle_auth_login(_client: Any, **kwargs: Any) -> dict[str, Any]:
    """Run the OAuth consent flow. Blocks until browser consent completes."""
    from . import auth

    account = str(kwargs.get("account") or "default")
    raw = kwargs.get("scopes")
    if raw is not None and not isinstance(raw, list):
        raise ValueError("scopes must be a list of group names.")
    groups = [str(item) for item in raw] if raw else None
    login_result = auth.login(account, groups)
    return {
        "status": "ok" if login_result["ok"] else "error",
        "account": account,
        "groups": groups or auth.default_groups(),
        "message": login_result["message"],
    }


def handle_auth_logout(_client: Any, **kwargs: Any) -> dict[str, Any]:
    from . import auth

    account = str(kwargs.get("account") or "default")
    message = auth.logout(account)
    return {"status": "ok", "account": account, "message": message}


# --- Workspace handlers (Gmail / Calendar / Drive) ----------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})?)?$"
)


def handle_gmail_search_messages(client: Any, **kwargs: Any) -> dict[str, Any]:
    max_results = int(kwargs.get("max_results", 10))
    if not 1 <= max_results <= 25:
        raise ValueError("max_results must be between 1 and 25.")
    messages = client.search_messages(
        query=kwargs.get("query"), max_results=max_results
    )
    return {"messages": messages, "count": len(messages), "query": kwargs.get("query")}


def handle_gmail_get_message(client: Any, **kwargs: Any) -> dict[str, Any]:
    message_id = str(kwargs["message_id"]).strip()
    if not message_id:
        raise ValueError("message_id must not be empty.")
    return {"message": client.get_message(message_id)}


def handle_gmail_create_draft(client: Any, **kwargs: Any) -> dict[str, Any]:
    to = str(kwargs["to"]).strip()
    subject = str(kwargs["subject"])
    body = str(kwargs["body"])
    if not _EMAIL_RE.match(to):
        raise ValueError(f"'{to}' is not a valid recipient email address.")
    if not body.strip():
        raise ValueError("Draft body must not be empty.")
    result = client.create_draft(to=to, subject=subject, body=body)
    return {**result, "note": "Draft created. It was NOT sent — send it yourself after review."}


def handle_gcal_list_calendars(client: Any, **_kwargs: Any) -> dict[str, Any]:
    calendars = client.list_calendars()
    return {"calendars": calendars, "count": len(calendars)}


def _validate_rfc3339(value: str, label: str) -> None:
    if not isinstance(value, str) or not _RFC3339_RE.match(value):
        raise ValueError(
            f"{label} must be an ISO-8601 datetime like '2026-08-26T09:00:00+05:30' "
            "or a date '2026-08-26'."
        )


def handle_gcal_list_events(client: Any, **kwargs: Any) -> dict[str, Any]:
    time_min = kwargs.get("time_min")
    time_max = kwargs.get("time_max")
    if time_min:
        _validate_rfc3339(str(time_min), "time_min")
    if time_max:
        _validate_rfc3339(str(time_max), "time_max")
    max_results = int(kwargs.get("max_results", 10))
    if not 1 <= max_results <= 50:
        raise ValueError("max_results must be between 1 and 50.")
    events = client.list_events(
        calendar_id=str(kwargs.get("calendar_id") or "primary"),
        time_min=time_min,
        time_max=time_max,
        query=kwargs.get("query"),
        max_results=max_results,
    )
    return {"events": events, "count": len(events)}


def handle_drive_search_files(client: Any, **kwargs: Any) -> dict[str, Any]:
    max_results = int(kwargs.get("max_results", 20))
    if not 1 <= max_results <= 50:
        raise ValueError("max_results must be between 1 and 50.")
    files = client.search_files(query=kwargs.get("query"), max_results=max_results)
    return {"files": files, "count": len(files), "query": kwargs.get("query")}


# --- Schemas -----------------------------------------------------------------

_ACCOUNT_PROPERTY = {
    "account": {
        "type": "string",
        "description": "Optional stored token profile to use (default: 'default'). "
        "See auth_login for creating profiles.",
    }
}

_SITE_URL_PROPERTY = {
    "site_url": {
        "type": "string",
        "description": "Search Console property URL exactly as listed by sc_list_sites "
        "(e.g. https://example.com/ or sc-domain:example.com).",
    },
    **_ACCOUNT_PROPERTY,
}

SCHEMAS: dict[str, dict[str, Any]] = {
    "gsc_list_sites": {
        "type": "object",
        "properties": {**_ACCOUNT_PROPERTY},
        "additionalProperties": False,
    },
    "gsc_search_analytics": {
        "type": "object",
        "properties": {
            **_SITE_URL_PROPERTY,
            "start_date": {"type": "string", "description": "Range start, YYYY-MM-DD."},
            "end_date": {"type": "string", "description": "Range end, YYYY-MM-DD."},
            "dimensions": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(VALID_DIMENSIONS)},
                "description": "Optional grouping dimensions.",
            },
            "query": {
                "type": "string",
                "description": "Optional substring filter applied to query dimension.",
            },
            "row_limit": {
                "type": "integer",
                "description": f"Rows to return, 1-{MAX_ROW_LIMIT}. Default 100.",
            },
            "start_row": {"type": "integer", "description": "Offset for paging. Default 0."},
        },
        "required": ["site_url", "start_date", "end_date"],
        "additionalProperties": False,
    },
    "gsc_list_sitemaps": {
        "type": "object",
        "properties": {**_SITE_URL_PROPERTY},
        "required": ["site_url"],
        "additionalProperties": False,
    },
    "gsc_inspect_url": {
        "type": "object",
        "properties": {
            **_SITE_URL_PROPERTY,
            "inspection_url": {
                "type": "string",
                "description": "Full URL to inspect for index status.",
            },
        },
        "required": ["site_url", "inspection_url"],
        "additionalProperties": False,
    },
    "ga4_list_properties": {
        "type": "object",
        "properties": {**_ACCOUNT_PROPERTY},
        "additionalProperties": False,
    },
    "ga4_run_report": {
        "type": "object",
        "properties": {
            "property_id": {
                "type": "string",
                "description": "Numeric GA4 property ID as listed by ga4_list_properties.",
            },
            **_ACCOUNT_PROPERTY,
            "start_date": {
                "type": "string",
                "description": "YYYY-MM-DD, 'today', 'yesterday', or '<N>daysAgo'.",
            },
            "end_date": {
                "type": "string",
                "description": "YYYY-MM-DD, 'today', 'yesterday', or '<N>daysAgo'.",
            },
            "dimensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional GA4 dimensions, e.g. date, country, sessionDefaultChannelGroup, pagePath.",
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "GA4 metrics, e.g. activeUsers, sessions, screenPageViews, conversions, keyEvents.",
            },
            "row_limit": {
                "type": "integer",
                "description": f"Rows to return, 1-{GA4_MAX_ROW_LIMIT}. Default 100.",
            },
            "offset": {"type": "integer", "description": "Offset for paging. Default 0."},
        },
        "required": ["property_id", "start_date", "end_date", "metrics"],
        "additionalProperties": False,
    },
    "auth_status": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "auth_login": {
        "type": "object",
        "properties": {
            "account": {
                "type": "string",
                "description": "Optional token profile name (default: 'default'). "
                "Use a distinct name per Google account, e.g. 'support'.",
            },
            "scopes": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["search", "analytics", "gmail", "calendar", "drive"],
                },
                "description": "Scope groups to request. Defaults to "
                "['search', 'analytics'] — the marketing core. 'gmail' and "
                "'drive' are restricted scopes granting broad access to the "
                "whole mailbox or drive; only add them if a tool needs them.",
            },
        },
        "additionalProperties": False,
    },
    "auth_logout": {
        "type": "object",
        "properties": {
            "account": {
                "type": "string",
                "description": "Token profile to remove (default: 'default').",
            },
        },
        "additionalProperties": False,
    },
    "gmail_search_messages": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Gmail search syntax, e.g. 'from:customer is:unread' or 'subject:invoice'.",
            },
            "max_results": {"type": "integer", "description": "1-25. Default 10."},
            **_ACCOUNT_PROPERTY,
        },
        "additionalProperties": False,
    },
    "gmail_get_message": {
        "type": "object",
        "properties": {
            "message_id": {"type": "string"},
            **_ACCOUNT_PROPERTY,
        },
        "required": ["message_id"],
        "additionalProperties": False,
    },
    "gmail_create_draft": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address."},
            "subject": {"type": "string"},
            "body": {"type": "string", "description": "Plain-text body."},
            **_ACCOUNT_PROPERTY,
        },
        "required": ["to", "subject", "body"],
        "additionalProperties": False,
    },
    "gcal_list_calendars": {
        "type": "object",
        "properties": {**_ACCOUNT_PROPERTY},
        "additionalProperties": False,
    },
    "gcal_list_events": {
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Default 'primary'."},
            "time_min": {
                "type": "string",
                "description": "ISO-8601 lower bound, e.g. 2026-08-26T00:00:00+05:30.",
            },
            "time_max": {"type": "string", "description": "ISO-8601 upper bound."},
            "query": {"type": "string", "description": "Free-text event filter."},
            "max_results": {"type": "integer", "description": "1-50. Default 10."},
            **_ACCOUNT_PROPERTY,
        },
        "additionalProperties": False,
    },
    "drive_search_files": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Name/full-text filter."},
            "max_results": {"type": "integer", "description": "1-50. Default 20."},
            **_ACCOUNT_PROPERTY,
        },
        "additionalProperties": False,
    },
}

DESCRIPTIONS: dict[str, str] = {
    "gsc_list_sites": "List Search Console properties accessible to the authenticated user.",
    "gsc_search_analytics": (
        "Query GSC performance data: clicks, impressions, ctr, position grouped by "
        "optional dimensions over a date range. Read-only."
    ),
    "gsc_list_sitemaps": "List sitemaps submitted for a Search Console property.",
    "gsc_inspect_url": "Inspect a URL's Google index status via URL Inspection API.",
    "ga4_list_properties": (
        "List GA4 accounts and properties visible to the authenticated user, "
        "with numeric property IDs for reporting."
    ),
    "ga4_run_report": (
        "Run a GA4 report: metrics (and optional dimensions) over a date range "
        "for one property. Read-only."
    ),
    "auth_status": (
        "List stored Google token profiles: which accounts are logged in, "
        "their granted scopes, and refresh-token presence."
    ),
    "auth_login": (
        "Start Google OAuth consent for this machine: opens the browser and "
        "returns once the user finishes consenting. Tokens are stored locally "
        "under the given account profile. Requires an OAuth client secret on "
        "this machine. Only the requested scope groups are asked for — the "
        "default is search + analytics, so Gmail and Drive are never granted "
        "unless explicitly named."
    ),
    "auth_logout": "Delete a stored Google token profile from this machine.",
    "gmail_search_messages": (
        "Search a Gmail mailbox and return message metadata (from, subject, "
        "date, snippet). Read-only."
    ),
    "gmail_get_message": "Fetch one Gmail message's headers and snippet. Read-only.",
    "gmail_create_draft": (
        "Create a Gmail DRAFT (never sends it) for human review and sending. "
        "Draft-first guardrail: no outbound email leaves without a human."
    ),
    "gcal_list_calendars": "List calendars visible to the account. Read-only.",
    "gcal_list_events": (
        "List calendar events in a time range, optionally text-filtered. Read-only."
    ),
    "drive_search_files": (
        "Search Google Drive files by name/full-text, most recent first. "
        "Read-only; returns metadata and links, not contents."
    ),
}

TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "gsc_list_sites": handle_list_sites,
    "gsc_search_analytics": handle_search_analytics,
    "gsc_list_sitemaps": handle_list_sitemaps,
    "gsc_inspect_url": handle_inspect_url,
    "ga4_list_properties": handle_ga4_list_properties,
    "ga4_run_report": handle_ga4_run_report,
    "auth_status": handle_auth_status,
    "auth_login": handle_auth_login,
    "auth_logout": handle_auth_logout,
    "gmail_search_messages": handle_gmail_search_messages,
    "gmail_get_message": handle_gmail_get_message,
    "gmail_create_draft": handle_gmail_create_draft,
    "gcal_list_calendars": handle_gcal_list_calendars,
    "gcal_list_events": handle_gcal_list_events,
    "drive_search_files": handle_drive_search_files,
}
