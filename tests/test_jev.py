"""Jev intent labelling with a fake poster — no network, no real key."""
from __future__ import annotations

import pytest

from gws_marketing import jev, tools
from gws_marketing.tools import SCHEMAS, TOOLS, handle_classify_queries


def _answer(intent, confidence=0.9, page=None):
    answers = {"intent": {"type": "choice", "choice": intent, "confidence": confidence}}
    if page is not None:
        answers["best_page"] = {"type": "choice", "choice": page, "confidence": 0.8}
    return {"model": jev.JEV_MODEL, "answers": answers}


def test_payload_asks_intent_only_without_pages():
    payload = jev.build_payload("manglik calculator", "sc-domain:x.in", ["x"], None)
    assert payload["model"] == jev.JEV_MODEL
    assert payload["state"] == {"query": "manglik calculator", "site": "sc-domain:x.in", "brand_terms": ["x"]}
    assert set(payload["questions"]) == {"intent"}
    assert set(payload["questions"]["intent"]["criteria"]) == set(jev.INTENTS)


def test_classify_maps_page_choices_back_to_urls():
    pages = [{"url": "https://x.in/a", "about": "calculator"}, {"url": "https://x.in/b"}]
    seen = []

    def post(payload, key):
        seen.append((payload, key))
        assert set(payload["questions"]["best_page"]["criteria"]) == {"page_0", "page_1", "none"}
        return _answer("tool", page="page_1")

    out = jev.classify_queries(["q1"], site="s", pages=pages, api_key="k", post=post)
    assert out == [{"query": "q1", "intent": "tool", "confidence": 0.9,
                    "best_page": "https://x.in/b", "best_page_confidence": 0.8}]
    assert seen[0][1] == "k"


def test_no_page_choice_returns_none():
    out = jev.classify_queries(["q"], site="s", pages=[{"url": "u"}], api_key="k",
                               post=lambda p, k: _answer("other", page="none"))
    assert out[0]["best_page"] is None


@pytest.mark.parametrize("response", [
    {"answers": {"intent": {"type": "choice", "choice": "made-up", "confidence": 0.5}}},
    {"answers": {"intent": {"type": "choice", "choice": "brand", "confidence": 1.5}}},
    {"answers": {}},
    {"nope": 1},
])
def test_bad_answers_are_reported_per_query_not_raised(response):
    out = jev.classify_queries(["bad", "good"], site="s", api_key="k",
                               post=lambda p, k: response if p["state"]["query"] == "bad" else _answer("brand"))
    assert out[0]["intent"] is None and "error" in out[0]
    assert out[1]["intent"] == "brand"


def test_missing_key_is_a_runtime_error(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("GWS_MARKETING_HOME", str(tmp_path))
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        jev.load_api_key()


def test_key_file_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("GWS_MARKETING_HOME", str(tmp_path))
    (tmp_path / jev.KEY_FILE).write_text("secret\n", encoding="utf-8")
    assert jev.load_api_key() == "secret"


def test_too_many_pages_rejected():
    with pytest.raises(ValueError, match="At most"):
        jev.classify_queries(["q"], site="s", pages=[{"url": str(i)} for i in range(jev.MAX_PAGES + 1)],
                             api_key="k", post=lambda p, k: _answer("brand"))


class FakeGsc:
    def search_analytics(self, **kwargs):
        assert kwargs["dimensions"] == ["query"]
        return [
            {"keys": ["vedpatrika"], "clicks": 3, "impressions": 10, "position": 1.24},
            {"keys": ["manglik calculator"], "clicks": 0, "impressions": 20, "position": 66.7},
            {"keys": ["what is manglik"], "clicks": 1, "impressions": 5, "position": 12.0},
        ]


def test_handler_merges_metrics_and_summarises(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    labels = {"vedpatrika": "brand", "manglik calculator": "tool", "what is manglik": "tool"}
    monkeypatch.setattr(jev, "_post_json", lambda p, k: _answer(labels[p["state"]["query"]]))
    out = handle_classify_queries(FakeGsc(), site_url="sc-domain:x.in",
                                  start_date="2026-09-01", end_date="2026-09-20")
    assert out["count"] == 3
    assert out["queries"][1] == {"query": "manglik calculator", "intent": "tool", "confidence": 0.9,
                                 "clicks": 0, "impressions": 20, "position": 66.7}
    assert out["summary"] == {"brand": {"queries": 1, "clicks": 3, "impressions": 10},
                              "tool": {"queries": 2, "clicks": 1, "impressions": 25}}


def test_handler_checks_key_before_calling_google(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("GWS_MARKETING_HOME", str(tmp_path))

    class Boom:
        def search_analytics(self, **kwargs):
            raise AssertionError("Google should not be called without a key")

    with pytest.raises(RuntimeError):
        handle_classify_queries(Boom(), site_url="s", start_date="2026-09-01", end_date="2026-09-02")


def test_handler_validates_inputs():
    with pytest.raises(ValueError):
        handle_classify_queries(FakeGsc(), site_url="s", start_date="2026-09-01",
                                end_date="2026-09-02", row_limit=101)
    with pytest.raises(ValueError):
        handle_classify_queries(FakeGsc(), site_url="s", start_date="2026-09-01",
                                end_date="2026-09-02", pages=[{"about": "no url"}])


def test_registered_with_schema():
    assert TOOLS["gsc_classify_queries"] is handle_classify_queries
    assert SCHEMAS["gsc_classify_queries"]["required"] == ["site_url", "start_date", "end_date"]
    assert tools.DESCRIPTIONS["gsc_classify_queries"]
