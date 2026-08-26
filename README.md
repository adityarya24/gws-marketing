# gws-marketing

Agent-facing MCP server for Google Search Console (GSC) marketing data.
Phase 1 scope: **read-only** GSC tools over stdio MCP so local agents
(OpenCode/Claude/Codex/Cursor) can query SEO performance without leaving chat.

Pattern mirror of `astro-skill`: low-level `mcp` stdio server, explicit JSON
schemas, tool registry as single source of truth, mocked tests.

## Status

- Phase 0 survey + plan: done (see `PLAN.md`)
- Phase 1 scaffold: GSC read-only tools implemented with mock-based tests
- Live OAuth smoke: **verified** against a real Search Console property
  (site listing + search analytics + URL inspection), 2026-08-23.

## Tools (Phase 1)

| Tool | Description |
|---|---|
| `gsc_list_sites` | List searchable GSC properties for the authenticated user |
| `gsc_search_analytics` | Click/impression/CTR/position rows by dimensions |
| `gsc_list_sitemaps` | List submitted sitemaps for a property |
| `gsc_inspect_url` | URL inspection (indexing status) |

All tools are read-only. Scopes used: `webmasters.readonly` (Search Console)
and `analytics.readonly` (GA4).

## Authentication (built into the server)

Agents manage auth themselves over MCP — no CLI required:

- `auth_status` — list stored token profiles: accounts, scopes, refresh-token presence.
- `auth_login` — open the Google consent page in the browser and store tokens
  when the user finishes. Optional `account` name creates a separate profile
  (e.g. `{"account": "support"}` for a second Google account).
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

## Roadmap

See `PLAN.md`. Shipped so far: GSC reads, GA4 reports, built-in auth tools,
and Workspace reads/drafts (Gmail search + draft-only, Calendar, Drive).
Later: Business Profile reads and write operations behind confirmation gates.
