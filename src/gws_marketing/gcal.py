"""Google Calendar read-only client over plain REST."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

# NOTE: www.googleapis.com is the canonical host that reliably serves
# Calendar v3; calendar.googleapis.com intermittently returns HTML 404s.
BASE = "https://www.googleapis.com/calendar/v3"


class GcalRestClient:
    def __init__(self, session: Any) -> None:
        self._session = session

    @classmethod
    def from_credentials(cls, credentials: Any) -> "GcalRestClient":
        from google.auth.transport.requests import AuthorizedSession

        return cls(AuthorizedSession(credentials))

    def _check(self, response: Any, context: str) -> dict[str, Any]:
        if response.status_code >= 400:
            snippet = (response.text or "")[:300]
            raise RuntimeError(f"Calendar {context} failed ({response.status_code}): {snippet}")
        return response.json()

    def list_calendars(self) -> list[dict[str, Any]]:
        response = self._session.get(f"{BASE}/users/me/calendarList", params={"maxResults": 100})
        payload = self._check(response, "calendarList.list")
        return [
            {
                "id": entry.get("id"),
                "summary": entry.get("summary"),
                "primary": bool(entry.get("primary")),
                "access_role": entry.get("accessRole"),
                "time_zone": entry.get("timeZone"),
            }
            for entry in payload.get("items", [])
        ]

    def list_events(
        self,
        calendar_id: str = "primary",
        time_min: str | None = None,
        time_max: str | None = None,
        query: str | None = None,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        if query:
            params["q"] = query
        encoded_id = quote(calendar_id, safe="")
        response = self._session.get(
            f"{BASE}/calendars/{encoded_id}/events", params=params
        )
        payload = self._check(response, "events.list")
        events: list[dict[str, Any]] = []
        for entry in payload.get("items", []):
            start = entry.get("start", {})
            end = entry.get("end", {})
            events.append(
                {
                    "id": entry.get("id"),
                    "summary": entry.get("summary"),
                    "start": start.get("dateTime") or start.get("date"),
                    "end": end.get("dateTime") or end.get("date"),
                    "location": entry.get("location"),
                    "hangout_link": entry.get("hangoutLink"),
                    "status": entry.get("status"),
                }
            )
        return events
