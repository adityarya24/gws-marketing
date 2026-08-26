"""Thin Search Console REST client wrapper.

Handlers in :mod:`gws_marketing.tools` depend only on the small surface of
:class:`GscClient` so tests can inject a fake without Google libraries or
network access.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Phase 1 is strictly read-only. Widen deliberately, one phase at a time.
# OAuth scopes shared across all gws-marketing clients.
# Scopes are grouped so a consent screen only ever asks for what the user
# actually wants. Asking for Gmail and Drive in order to read Search Console
# numbers is a bad trade for them and a bad look for us: gmail.readonly and
# drive.readonly are *restricted* scopes in Google's terms, which drags any
# publicly distributed app into verification and a security assessment.
#
# Read-only everywhere except Gmail drafts (gmail.compose enables draft
# management; SENDING is deliberately not implemented in any phase < 4).
SCOPE_GROUPS: dict[str, list[str]] = {
    "search": ["https://www.googleapis.com/auth/webmasters.readonly"],
    "analytics": ["https://www.googleapis.com/auth/analytics.readonly"],
    "gmail": [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
    ],
    "calendar": ["https://www.googleapis.com/auth/calendar.readonly"],
    "drive": ["https://www.googleapis.com/auth/drive.readonly"],
}

# The marketing core, and the default: neither is a restricted scope, so the
# common case needs no verification and no scary consent screen.
DEFAULT_SCOPE_GROUPS: tuple[str, ...] = ("search", "analytics")

# Groups Google treats as restricted or sensitive. Named so callers can warn.
RESTRICTED_GROUPS = frozenset({"gmail", "drive"})

# Which group each tool family needs, keyed by the tool-name prefix.
TOOL_GROUPS: dict[str, str] = {
    "gsc_": "search",
    "ga4_": "analytics",
    "gmail_": "gmail",
    "gcal_": "calendar",
    "drive_": "drive",
}

ALL_SCOPES = [scope for group in SCOPE_GROUPS.values() for scope in group]

# Retained so existing callers and stored tokens keep working.
SCOPES = ALL_SCOPES


def resolve_scopes(groups: list[str] | tuple[str, ...] | None = None) -> list[str]:
    """Expand group names into OAuth scopes, rejecting unknown groups."""
    names = list(groups) if groups else list(DEFAULT_SCOPE_GROUPS)
    unknown = [name for name in names if name not in SCOPE_GROUPS]
    if unknown:
        raise ValueError(
            f"Unknown scope group(s): {', '.join(sorted(unknown))}. "
            f"Valid groups: {', '.join(sorted(SCOPE_GROUPS))}."
        )
    scopes: list[str] = []
    for name in names:
        for scope in SCOPE_GROUPS[name]:
            if scope not in scopes:
                scopes.append(scope)
    return scopes


def groups_for_scopes(scopes: list[str] | None) -> list[str]:
    """Report which groups a set of granted scopes fully satisfies."""
    granted = set(scopes or [])
    return sorted(
        name for name, needed in SCOPE_GROUPS.items() if set(needed) <= granted
    )


def group_for_tool(tool_name: str) -> str | None:
    for prefix, group in TOOL_GROUPS.items():
        if tool_name.startswith(prefix):
            return group
    return None

# searchanalytics.query row cap per the Search Console API contract.
MAX_ROW_LIMIT = 25000


def config_dir() -> Path:
    """User-local config directory for secrets/tokens (never inside the repo)."""
    override = os.environ.get("GWS_MARKETING_HOME")
    base = Path(override) if override else Path.home() / ".config" / "gws-marketing"
    return base


def client_secret_path() -> Path | None:
    """OAuth client secret location: env override, else conventional default."""
    env = os.environ.get("GWS_CLIENT_SECRET_FILE")
    if env:
        return Path(env)
    default = config_dir() / "client_secret.json"
    return default if default.exists() else None


class GscRestClient:
    """Minimal wrapper over the discovered Search Console API service."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def list_sites(self) -> list[dict[str, Any]]:
        response = self._service.sites().list().execute()
        return list(response.get("siteEntry", []))

    def search_analytics(
        self,
        site_url: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
        query: str | None = None,
        row_limit: int = 100,
        start_row: int = 0,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "startDate": start_date,
            "endDate": end_date,
            "rowLimit": max(1, min(int(row_limit), MAX_ROW_LIMIT)),
            "startRow": max(0, int(start_row)),
        }
        if dimensions:
            body["dimensions"] = dimensions
        if query:
            body["dimensionFilterGroups"] = [
                {
                    "filters": [
                        {
                            "dimension": "query",
                            "operator": "contains",
                            "expression": query,
                        }
                    ]
                }
            ]
        response = (
            self._service.searchanalytics()
            .query(siteUrl=site_url, body=body)
            .execute()
        )
        return list(response.get("rows", []))

    def list_sitemaps(self, site_url: str) -> list[dict[str, Any]]:
        response = self._service.sitemaps().list(siteUrl=site_url).execute()
        return list(response.get("sitemap", []))

    def inspect_url(self, site_url: str, inspection_url: str) -> dict[str, Any]:
        response = (
            self._service.urlInspection()
            .index()
            .inspect(body={"inspectionUrl": inspection_url, "siteUrl": site_url})
            .execute()
        )
        return dict(response.get("inspectionResult", {}))


def build_client(credentials: Any) -> GscRestClient:
    """Build the real client from user OAuth credentials (lazy imports)."""
    import googleapiclient.discovery

    service = googleapiclient.discovery.build(
        "searchconsole",
        "v1",
        credentials=credentials,
        cache_discovery=False,
    )
    return GscRestClient(service)
