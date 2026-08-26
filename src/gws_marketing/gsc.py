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
# Read-only everywhere except Gmail drafts (gmail.compose enables draft
# management; SENDING is deliberately not implemented in any phase < 4).
SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

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
