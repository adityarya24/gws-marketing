"""GA4 read-only client over plain REST endpoints.

Uses ``google.auth.transport.requests.AuthorizedSession`` so the same stored
OAuth credentials power Search Console and GA4 without adding another client
library dependency.
"""
from __future__ import annotations

from typing import Any

ADMIN_BASE = "https://analyticsadmin.googleapis.com/v1beta"
DATA_BASE = "https://analyticsdata.googleapis.com/v1beta"

# GA4 Data API v1beta runReport contract caps.
MAX_DIMENSIONS = 8
MAX_METRICS = 10
MAX_ROW_LIMIT = 10000


class Ga4RestClient:
    """Minimal wrapper for the GA4 admin + data REST surfaces we need."""

    def __init__(self, session: Any) -> None:
        self._session = session

    @classmethod
    def from_credentials(cls, credentials: Any) -> "Ga4RestClient":
        from google.auth.transport.requests import AuthorizedSession

        return cls(AuthorizedSession(credentials))

    def _check(self, response: Any, context: str) -> dict[str, Any]:
        if response.status_code >= 400:
            snippet = (response.text or "")[:300]
            raise RuntimeError(f"GA4 {context} failed ({response.status_code}): {snippet}")
        return response.json()

    def list_properties(self) -> list[dict[str, Any]]:
        """Summarize every account/property visible to the authenticated user."""
        response = self._session.get(
            f"{ADMIN_BASE}/accountSummaries", params={"pageSize": 200}
        )
        payload = self._check(response, "accountSummaries")
        summaries: list[dict[str, Any]] = []
        for account in payload.get("accountSummaries", []):
            for prop in account.get("propertySummaries", []):
                summaries.append(
                    {
                        "account": account.get("displayName"),
                        "property": prop.get("displayName"),
                        "property_id": (prop.get("property") or "").rsplit("/", 1)[-1],
                    }
                )
        return summaries

    def run_report(
        self,
        property_id: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
        metrics: list[str] | None = None,
        row_limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Run one report against ``properties/{property_id}`` and flatten rows."""
        body: dict[str, Any] = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "limit": row_limit,
            "offset": offset,
        }
        if dimensions:
            body["dimensions"] = [{"name": name} for name in dimensions]
        if metrics:
            body["metrics"] = [{"name": name} for name in metrics]

        response = self._session.post(
            f"{DATA_BASE}/properties/{property_id}:runReport", json=body
        )
        payload = self._check(response, "runReport")

        rows: list[dict[str, Any]] = []
        for raw in payload.get("rows", []):
            rows.append(
                {
                    "keys": [dv.get("value") for dv in raw.get("dimensionValues", [])],
                    "values": [mv.get("value") for mv in raw.get("metricValues", [])],
                }
            )
        return {"row_count": payload.get("rowCount", len(rows)), "rows": rows}
