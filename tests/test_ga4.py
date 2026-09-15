"""Production hostname filtering without live Google API calls."""
from unittest.mock import Mock

import pytest

from gws_marketing.ga4 import Ga4RestClient
from gws_marketing.tools import SCHEMAS, handle_ga4_run_report


@pytest.mark.parametrize("hostname", [None, "example.com", "www.example.com"])
def test_hostname_filter_reaches_rest_without_grouping(hostname):
    session = Mock()
    session.post.return_value.status_code = 200
    session.post.return_value.json.return_value = {
        "rowCount": 1, "rows": [{"metricValues": [{"value": "78"}]}],
    }
    args = {} if hostname is None else {"hostname": hostname.upper()}
    result = handle_ga4_run_report(
        Ga4RestClient(session), property_id="123", start_date="7daysAgo",
        end_date="yesterday", metrics=["screenPageViews"], **args,
    )
    body = session.post.call_args.kwargs["json"]
    assert "dimensions" not in body
    if hostname is None:
        assert "dimensionFilter" not in body
        assert "hostname" not in result
    else:
        assert body["dimensionFilter"] == {"filter": {
            "fieldName": "hostName", "stringFilter": {
                "matchType": "EXACT", "value": hostname, "caseSensitive": False,
            },
        }}
        assert result["hostname"] == hostname
    assert result["rows"] == [{"keys": [], "values": ["78"]}]


@pytest.mark.parametrize("hostname", [
    "", "https://example.com", "example.com/path", "example.com:443",
    "*.example.com", " example.com", "example..com", "-example.com",
    "a" * 64 + ".com", 123, ["example.com"],
])
def test_invalid_hostname_rejected_before_request(hostname):
    client = Mock()
    with pytest.raises(ValueError, match="hostname"):
        handle_ga4_run_report(
            client, property_id="123", start_date="7daysAgo", end_date="today",
            metrics=["sessions"], hostname=hostname,
        )
    client.run_report.assert_not_called()


def test_hostname_exposed_as_optional_tool_input():
    schema = SCHEMAS["ga4_run_report"]
    assert schema["properties"]["hostname"]["type"] == "string"
    assert "hostname" not in schema["required"]
