# Production-only GA4 reports

Pass `hostname` to `ga4_run_report` to filter events before Google aggregates
the report. This is an exact, case-insensitive hostname match, not a URL or
wildcard. An apex hostname does not include its `www` subdomain.

```json
{
  "property_id": "123456789",
  "start_date": "28daysAgo",
  "end_date": "3daysAgo",
  "metrics": ["sessions", "activeUsers", "screenPageViews", "keyEvents"],
  "hostname": "example.com"
}
```

The response echoes the applied hostname. Omitting it preserves all-host
reporting. You do not need to group by `hostName`; avoid summing per-host
active users, which can overlap.

This filters reports, including historical data; it does not delete GA4 data
or stop development/preview sites from collecting new events. Production-host
preview paths and internal visits also remain included. Collection guards and
payment-success instrumentation must be handled in the website separately.

Restart/reconnect an existing MCP server after updating its installed code so
clients discover the new optional tool input.

API contract: https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/FilterExpression
