# Changelog

All notable changes to this project are documented here.

## [0.2.1] - 2026-08-26

### Fixed
- Sync package version (`__init__.py` now matches `pyproject.toml`).
- `auth_login` returns `status: "error"` when the OAuth client secret is missing
  instead of always reporting success.
- `auth_login` tests no longer call the real OAuth flow when a client secret is
  present on the machine.
- MCP tool errors (`validation_error`, `runtime_error`, `unknown_tool`) are
  returned as structured JSON instead of uncaught exceptions.
- Calendar IDs with special characters are URL-encoded before API calls.
- Drive search query literals escape backslashes as well as single quotes.

### Changed
- Gmail search fetches message metadata in parallel to reduce latency on
  multi-result searches.

### Added
- GitHub Actions CI (pytest on Python 3.11 and 3.12).
- Example MCP client configuration in the README.
- This changelog.

## [0.2.0] - 2026-08-26

### Changed
- OAuth scopes are grouped (`search`, `analytics`, `gmail`, `calendar`,
  `drive`); `auth_login` requests only the groups you name.
- Default consent is `search + analytics` only — no mailbox or Drive unless
  explicitly requested.
- `get_client` refuses tools whose scope group was never granted, with an
  actionable error message.
- `load_credentials` uses the scopes actually stored on the token.

### Added
- GA4, Gmail (read + draft), Calendar, and Drive tools.
- Built-in `auth_status` / `auth_login` / `auth_logout` with multi-account
  profiles.

## [0.1.0] - 2026-08-23

### Added
- Initial release: GSC read-only tools, stdio MCP server, mocked tests.
