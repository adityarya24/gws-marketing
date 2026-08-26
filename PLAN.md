# gws-marketing — Plan & Roadmap

Agent-facing MCP server for **Google Search Console, GA4, and Google
Workspace** (Gmail/Calendar/Drive), so any coding agent can query real
marketing/workspace data and produce human-reviewed drafts over stdio MCP,
with the OAuth flow built into the server itself.

## Status (v0.2.1)

- GSC reads: sites, search analytics, sitemaps, URL inspection (4 tools)
- GA4 reports: account/property listing, run_report (2 tools)
- Workspace: Gmail search/get/draft-only, Calendar list/events, Drive search (6 tools)
- Built-in auth: auth_status / auth_login / auth_logout with multi-account
  token profiles (3 tools)
- 43 mocked tests green; every surface live-smoked against real accounts.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | GSC read-only | ✅ shipped |
| 2 | GA4 reports | ✅ shipped |
| 2A | Agent-config registration, public release prep | ✅ done |
| 3 | Workspace reads + Gmail drafts, multi-account auth | ✅ shipped |
| 4 | Composite workflows (SEO digest → draft email, inbox triage, templates) | next |
| 5 | Approval-gated writes (Gmail send, Calendar events, Drive mutations) + Google Ads tools | blocked on Ads dev-token approval |

## Design principles

- Read-only first. The server NEVER sends email — `gmail_create_draft`
  produces drafts for human review and sending.
- Every data tool accepts an optional `account` parameter to select among
  stored OAuth profiles (multi-account by design).
- Tokens live only in the user's config directory, never in the repo.
- Tool registry is the single source of truth; explicit JSON schemas per tool;
  handlers take injectable clients so tests stay network-free.

## One-time setup per machine

1. Create/select a GCP project; enable these APIs: Google Search Console API,
   Google Analytics Admin API, Google Analytics Data API, Gmail API,
   Google Calendar API, Google Drive API.
2. Configure an External OAuth consent screen (testing mode is fine for
   personal use; add your account as test user).
3. Create a desktop OAuth client and store the downloaded client secret at
   `%USERPROFILE%\.config\gws-marketing\client_secret.json` (or point
   `GWS_CLIENT_SECRET_FILE` at it). Never commit it.
4. Run `auth_login` from any connected agent (or the bundled CLI) — browser
   consent completes the setup.

## Pending external approvals

- Business Profile API reads require Google's access-approval form plus a
  verified Business Profile (60+ days active).
- Google Ads tools require a developer token with Basic Access.
