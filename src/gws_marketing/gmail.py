"""Gmail read + draft-only client over plain REST.

Read/search uses gmail.readonly; drafts use gmail.compose. Sending is
deliberately NOT implemented — the draft-first guardrail keeps every
outbound message human-reviewed.
"""
from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

_HEADER_NAMES = ("From", "To", "Subject", "Date")


class GmailRestClient:
    def __init__(self, session: Any) -> None:
        self._session = session

    @classmethod
    def from_credentials(cls, credentials: Any) -> "GmailRestClient":
        from google.auth.transport.requests import AuthorizedSession

        return cls(AuthorizedSession(credentials))

    def _check(self, response: Any, context: str) -> dict[str, Any]:
        if response.status_code >= 400:
            snippet = (response.text or "")[:300]
            raise RuntimeError(f"Gmail {context} failed ({response.status_code}): {snippet}")
        return response.json()

    @staticmethod
    def _headers_to_dict(headers: list[dict[str, Any]]) -> dict[str, str]:
        return {h["name"]: h["value"] for h in headers or [] if h.get("name") in _HEADER_NAMES}

    def search_messages(self, query: str | None = None, max_results: int = 10) -> list[dict[str, Any]]:
        """Search the mailbox and return compact metadata rows."""
        params: dict[str, Any] = {"maxResults": max_results}
        if query:
            params["q"] = query
        response = self._session.get(f"{BASE}/messages", params=params)
        payload = self._check(response, "messages.list")

        results: list[dict[str, Any]] = []
        for stub in payload.get("messages", []):
            detail = self._check(
                self._session.get(
                    f"{BASE}/messages/{stub['id']}",
                    params={"format": "metadata", "metadataHeaders": list(_HEADER_NAMES)},
                ),
                "messages.get",
            )
            headers = self._headers_to_dict(detail.get("payload", {}).get("headers", []))
            results.append(
                {
                    "id": detail.get("id"),
                    "thread_id": detail.get("threadId"),
                    "from": headers.get("From"),
                    "subject": headers.get("Subject"),
                    "date": headers.get("Date"),
                    "snippet": detail.get("snippet"),
                    "labels": detail.get("labelIds", []),
                }
            )
        return results

    def get_message(self, message_id: str) -> dict[str, Any]:
        """Full metadata + body snippet for one message (no attachments)."""
        detail = self._check(
            self._session.get(f"{BASE}/messages/{message_id}", params={"format": "full"}),
            "messages.get",
        )
        headers = self._headers_to_dict(detail.get("payload", {}).get("headers", []))
        return {
            "id": detail.get("id"),
            "thread_id": detail.get("threadId"),
            "headers": headers,
            "snippet": detail.get("snippet"),
            "labels": detail.get("labelIds", []),
        }

    def create_draft(self, to: str, subject: str, body: str) -> dict[str, Any]:
        """Create a draft. It is NEVER sent — human sends it themselves."""
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        response = self._session.post(
            f"{BASE}/drafts", json={"message": {"raw": raw}}
        )
        payload = self._check(response, "drafts.create")
        draft_msg = payload.get("message", {})
        return {"draft_id": payload.get("id"), "message_id": draft_msg.get("id"), "to": to, "subject": subject}
