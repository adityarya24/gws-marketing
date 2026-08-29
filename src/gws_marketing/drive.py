"""Google Drive read-only client over plain REST."""
from __future__ import annotations

from typing import Any

BASE = "https://www.googleapis.com/drive/v3"

_FILE_FIELDS = "files(id,name,mimeType,modifiedTime,size,webViewLink)"


def _escape_drive_query_literal(value: str) -> str:
    """Escape a user string for Drive query single-quoted literals."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


class DriveRestClient:
    def __init__(self, session: Any) -> None:
        self._session = session

    @classmethod
    def from_credentials(cls, credentials: Any) -> DriveRestClient:
        from google.auth.transport.requests import AuthorizedSession

        return cls(AuthorizedSession(credentials))

    def _check(self, response: Any, context: str) -> dict[str, Any]:
        if response.status_code >= 400:
            snippet = (response.text or "")[:300]
            raise RuntimeError(f"Drive {context} failed ({response.status_code}): {snippet}")
        return response.json()

    def search_files(
        self,
        query: str | None = None,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """List files (most recently modified first), optionally name-filtered."""
        clauses = ["trashed = false"]
        if query:
            safe = _escape_drive_query_literal(query)
            clauses.append(f"(name contains '{safe}' or fullText contains '{safe}')")
        params: dict[str, Any] = {
            "q": " and ".join(clauses),
            "orderBy": "modifiedTime desc",
            "pageSize": max_results,
            "fields": _FILE_FIELDS,
        }
        response = self._session.get(f"{BASE}/files", params=params)
        payload = self._check(response, "files.list")
        return payload.get("files", [])
