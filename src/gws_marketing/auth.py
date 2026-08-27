"""OAuth credential storage and flows for gws-marketing.

Tokens live in the user config directory with restrictive permissions and are
never stored inside the repository. Multiple Google accounts are supported via
named profiles: ``tokens.json`` (default) plus ``tokens.<profile>.json``.
"""
from __future__ import annotations

import json
import os
import re
import stat
from typing import Any

from .gsc import (
    DEFAULT_SCOPE_GROUPS,
    RESTRICTED_GROUPS,
    client_secret_path,
    config_dir,
    groups_for_scopes,
    resolve_scopes,
)

TOKENS_FILE = "tokens.json"
_PROFILE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def _validate_profile(profile: str) -> str:
    """Reject profile names that could escape the config directory."""
    if not _PROFILE_RE.match(profile):
        raise ValueError(
            "Profile/account names may only contain letters, numbers, '_' and '-'."
        )
    return profile


def tokens_path(profile: str = "default") -> Any:
    if profile == "default":
        return config_dir() / TOKENS_FILE
    return config_dir() / f"tokens.{_validate_profile(profile)}.json"


def list_profiles() -> list[dict[str, Any]]:
    """Summarize every stored token profile found in the config directory."""
    base = config_dir()
    profiles: list[dict[str, Any]] = []
    if not base.exists():
        return profiles
    for path in sorted(base.glob("tokens*.json")):
        if path.name == TOKENS_FILE:
            name = "default"
        elif path.name.startswith("tokens.") and path.name.endswith(".json"):
            name = path.name[len("tokens.") : -len(".json")]
        else:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            profiles.append({"account": name, "error": "unreadable token file"})
            continue
        profiles.append(
            {
                "account": name,
                "scopes": sorted(data.get("scopes", [])),
                "has_refresh_token": bool(data.get("refresh_token")),
            }
        )
    return profiles


def _write_private_json(path: Any, payload: dict[str, Any]) -> None:
    """Write JSON that only the owner can read, with no readable window.

    Writing first and chmod-ing afterwards leaves the refresh token on disk
    at the process umask (commonly 0644) until the chmod lands. Creating the
    file with 0600 up front closes that window; the chmod still runs so an
    existing wider-permission file gets tightened too.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=2)
    mode = stat.S_IRUSR | stat.S_IWUSR  # 600
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, mode)
    try:
        handle = os.fdopen(fd, "w", encoding="utf-8")
    except BaseException:
        os.close(fd)  # fdopen did not take ownership, so close it here.
        raise
    with handle:
        handle.write(raw)
    try:
        path.chmod(mode)
    except OSError:
        pass  # Windows may not support POSIX modes fully; best effort.


def granted_scopes(profile: str = "default") -> list[str]:
    """Scopes stored for a profile, or [] when it has never logged in."""
    path = tokens_path(profile)
    if not path.exists():
        return []
    try:
        return list(json.loads(path.read_text(encoding="utf-8")).get("scopes", []))
    except (OSError, ValueError):
        return []


def granted_groups(profile: str = "default") -> list[str]:
    """Scope groups this profile has actually consented to."""
    return groups_for_scopes(granted_scopes(profile))


def default_groups() -> list[str]:
    """Groups to request when the caller names none.

    ``GWS_SCOPES`` lets an operator widen or narrow this without editing code,
    e.g. ``GWS_SCOPES=search,analytics,gmail``.
    """
    raw = os.environ.get("GWS_SCOPES", "").strip()
    if not raw:
        return list(DEFAULT_SCOPE_GROUPS)
    return [part.strip() for part in raw.split(",") if part.strip()]


def login(profile: str = "default", groups: list[str] | None = None) -> dict[str, Any]:
    """Run the installed-app OAuth flow and persist refreshable tokens.

    Only the requested groups are asked for. The default is the marketing core
    (search + analytics); Gmail, Calendar and Drive are opt-in, so nobody hands
    over their whole mailbox to read Search Console numbers.

    Returns a dict with ``ok`` (bool) and ``message`` (str) so callers can
    distinguish a missing client secret from a successful consent flow.
    """
    secret = client_secret_path()
    if secret is None or not secret.exists():
        return {
            "ok": False,
            "message": (
                "No OAuth client secret found. Set GWS_CLIENT_SECRET_FILE to the "
                "downloaded desktop client_secret.json from your GCP project, "
                "then retry."
            ),
        }

    # Imported lazily so tooling/tests never require these libs.
    from google_auth_oauthlib.flow import InstalledAppFlow

    requested = groups or default_groups()
    scopes = resolve_scopes(requested)

    flow = InstalledAppFlow.from_client_secrets_file(str(secret), scopes)
    credentials = flow.run_local_server(port=0)

    _write_private_json(
        tokens_path(profile),
        {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": list(credentials.scopes or []),
        },
    )
    restricted = sorted(set(requested) & RESTRICTED_GROUPS)
    note = ""
    if restricted:
        note = (
            f" Granted restricted scope group(s): {', '.join(restricted)} —"
            " these give broad access, so revoke with auth_logout when done."
        )
    return {
        "ok": True,
        "message": (
            f"Saved tokens for account '{profile}' to {tokens_path(profile)}."
            f" Scope groups: {', '.join(requested)}.{note}"
        ),
    }


def load_credentials(profile: str = "default") -> Any:
    """Load stored credentials, refreshing when expired. None if absent."""
    path = tokens_path(profile)
    if not path.exists():
        return None

    from google.oauth2.credentials import Credentials

    data = json.loads(path.read_text(encoding="utf-8"))
    credentials = Credentials.from_authorized_user_info(data, data.get("scopes"))
    if credentials.expired and credentials.refresh_token:
        from google.auth.transport.requests import Request

        credentials.refresh(Request())
        _write_private_json(path, json.loads(credentials.to_json()))
    return credentials


def logout(profile: str = "default") -> str:
    """Delete a stored token profile. Returns a human-readable result."""
    path = tokens_path(profile)
    if not path.exists():
        return f"No stored tokens for account '{profile}'."
    path.unlink()
    return f"Removed stored tokens for account '{profile}'."


def main() -> None:
    result = login()
    print(result["message"])
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
