# gws-marketing

Agent-facing MCP server for Google marketing data over stdio MCP, so local
agents (OpenCode/Claude/Codex/Cursor) can query Search Console, GA4, Gmail,
Calendar and Drive without leaving chat.

Everything is read-only **except** `gmail_create_draft`, which writes a draft.
Sending mail is deliberately not implemented — every outbound message stays
human-reviewed.

Pattern mirror of `astro-skill`: low-level `mcp` stdio server, explicit JSON
schemas, tool registry as single source of truth, mocked tests.

## Status

- Phase 0 survey + plan: done (see `PLAN.md`)
- Phase 1 scaffold: GSC read-only tools implemented with mock-based tests
- Since then: GA4, Gmail (read + draft), Calendar and Drive tools added
- Live OAuth smoke: **verified** against a real Search Console property
  (site listing + search analytics + URL inspection), 2026-08-23.

## Tools

| Tool | Scope group | Description |
|---|---|---|
| `gsc_list_sites` | `search` | List searchable GSC properties for the authenticated user |
| `gsc_search_analytics` | `search` | Click/impression/CTR/position rows by dimensions |
| `gsc_list_sitemaps` | `search` | List submitted sitemaps for a property |
| `gsc_inspect_url` | `search` | URL inspection (indexing status) |
| `ga4_list_properties` | `analytics` | List GA4 properties |
| `ga4_run_report` | `analytics` | Run a GA4 report by metrics/dimensions |
| `gmail_search_messages` | `gmail` | Search the mailbox |
| `gmail_get_message` | `gmail` | Fetch one message |
| `gmail_create_draft` | `gmail` | **Writes** a draft (never sends) |
| `gcal_list_calendars` | `calendar` | List calendars |
| `gcal_list_events` | `calendar` | List events in a window |
| `drive_search_files` | `drive` | Search Drive files |
| `auth_status` / `auth_login` / `auth_logout` | — | Credential management |

## Scopes: you are only asked for what you use

Scopes are grouped, and `auth_login` requests **only the groups you name**.

| Group | Google scopes | Notes |
|---|---|---|
| `search` | `webmasters.readonly` | Default |
| `analytics` | `analytics.readonly` | Default |
| `gmail` | `gmail.readonly`, `gmail.compose` | **Restricted** — full mailbox read |
| `calendar` | `calendar.readonly` | Sensitive |
| `drive` | `drive.readonly` | **Restricted** — full Drive read |

The default is `["search", "analytics"]`: the marketing core, and neither is a
restricted scope. Reading Search Console numbers should never cost you your
mailbox.

Add a group only when you want its tools:

```jsonc
{"tool": "auth_login", "arguments": {"scopes": ["search", "analytics", "gmail"]}}
```

Or set a machine-wide default: `GWS_SCOPES=search,analytics,gmail`.

Calling a tool whose group you never granted fails immediately with a message
naming the group to add, rather than surfacing an opaque 403 from Google.
`auth_status` lists the groups each profile actually holds.

**If you plan to distribute this to other people:** `gmail.readonly` and
`drive.readonly` are restricted scopes, so a published app using them needs
Google verification and a security assessment. Staying on the default two
groups avoids that entirely.

## Authentication (built into the server)

Agents manage auth themselves over MCP — no CLI required:

- `auth_status` — list stored token profiles: accounts, scopes, refresh-token presence.
- `auth_login` — open the Google consent page in the browser and store tokens
  when the user finishes. Optional `account` name creates a separate profile
  (e.g. `{"account": "support"}` for a second Google account). Optional
  `scopes` selects which groups to request (see above).
- `auth_logout` — delete a stored profile.

Tokens live at `%USERPROFILE%\.config\gws-marketing\tokens.json`
(`tokens.<account>.json` for extra profiles), mode 600, never in the repo.

## Setup

```bash
py -3.12 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

One-time per machine: put a desktop OAuth client secret from your own GCP
project at `%USERPROFILE%\.config\gws-marketing\client_secret.json`
(or point `GWS_CLIENT_SECRET_FILE` at it). The first `auth_login` call then
completes everything else interactively. CLI fallback:
`.venv\Scripts\gws-marketing-login`.

Never commit client secrets or tokens — `.gitignore` covers the common
filename patterns.

Run the server:

```bash
.venv\Scripts\gws-marketing-server
```

Register in an MCP client config as a stdio server pointing at the venv's
`gws-marketing-server` executable.

### Cursor / Claude Desktop / Codex (stdio MCP)

Point the client at the venv executable. Adjust the path to your clone:

```json
{
  "mcpServers": {
    "gws-marketing": {
      "command": "C:\\Users\\YOU\\gws-marketing\\.venv\\Scripts\\gws-marketing-server.exe",
      "args": []
    }
  }
}
```

On macOS/Linux, use `.venv/bin/gws-marketing-server` instead.

First run from the agent: call `auth_status`, then `auth_login` with only the
scope groups you need (default is `search` + `analytics`).

## Roadmap

See `PLAN.md`. Shipped so far: GSC reads, GA4 reports, built-in auth tools,
and Workspace reads/drafts (Gmail search + draft-only, Calendar, Drive).
Later: Business Profile reads and write operations behind confirmation gates.
