"""Search-intent labels for Search Console queries via TypeSafe Jev.

Jev answers typed questions (a choice or a yes/no probability) with a
confidence score instead of generating text, which is exactly the shape of
"what does someone typing this query want?". One request per query keeps each
answer independent; requests run in a small thread pool because a single call
takes well under a second.

The API key is read from ``TYPESAFE_API_KEY`` or, failing that, from
``typesafe.key`` in the gws-marketing config directory. It is only ever sent
to the TypeSafe endpoint.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.request import Request, urlopen

from .gsc import config_dir

JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-1.13.0"
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 64 * 1024
MAX_WORKERS = 8
MAX_PAGES = 30
KEY_FILE = "typesafe.key"

INTENTS: dict[str, str] = {
    "brand": "The searcher is looking for this specific site or brand by name.",
    "question": (
        "The searcher wants an explanation or an answer to a question "
        "(what, how, why, meaning, rules, remedies). Best served by answer content."
    ),
    "tool": (
        "The searcher wants a free online calculator, checker or tool to run "
        "on their own details right now."
    ),
    "purchase": (
        "The searcher wants to buy, order or download a paid report, product "
        "or service."
    ),
    "other": "Unrelated to what this site offers, or too vague to act on.",
}

NO_PAGE = "none"

Poster = Callable[[dict[str, Any], str], dict[str, Any]]


def load_api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        path = config_dir() / KEY_FILE
        if path.exists():
            key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError(
            "No TypeSafe API key. Set TYPESAFE_API_KEY or put the key in "
            f"{config_dir() / KEY_FILE}."
        )
    return key


def _post_json(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        JEV_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "gws-marketing/jev-intent",
        },
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("TypeSafe response exceeded the size limit")
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise TypeError("TypeSafe response was not an object")
    return decoded


def _page_criteria(pages: Sequence[Mapping[str, str]]) -> tuple[dict[str, Any], dict[str, str]]:
    criteria: dict[str, Any] = {}
    choice_to_url: dict[str, str] = {}
    for index, page in enumerate(pages):
        name = f"page_{index}"
        criteria[name] = {"choose_when": f"{page['url']}: {page.get('about', '')}".strip()}
        choice_to_url[name] = page["url"]
    criteria[NO_PAGE] = {"choose_when": "None of the listed pages answers this query well."}
    return criteria, choice_to_url


def build_payload(
    query: str,
    site: str,
    brand_terms: Sequence[str],
    page_criteria: Mapping[str, Any] | None,
) -> dict[str, Any]:
    questions: dict[str, Any] = {
        "intent": {
            "type": "choice",
            "instructions": {
                "question": "What does the person typing this search query want?",
                "focus": "Judge the query as typed. Hindi, Hinglish and English queries are equally valid.",
            },
            "criteria": {name: {"choose_when": text} for name, text in INTENTS.items()},
        },
    }
    if page_criteria:
        questions["best_page"] = {
            "type": "choice",
            "instructions": {
                "question": "Which page of this site should rank for this query?",
                "focus": "Pick the page whose content matches the intent, not just the words.",
            },
            "criteria": dict(page_criteria),
        }
    return {
        "model": JEV_MODEL,
        "state": {"query": query, "site": site, "brand_terms": list(brand_terms)},
        "questions": questions,
    }


def _unit_interval(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} was not numeric")
    result = float(value)
    if not 0 <= result <= 1:
        raise ValueError(f"{name} was outside 0..1")
    return result


def _choice(answers: Mapping[str, Any], name: str, allowed: Sequence[str]) -> tuple[str, float]:
    row = answers.get(name)
    if not isinstance(row, Mapping) or row.get("type") != "choice":
        raise ValueError(f"TypeSafe omitted choice {name}")
    value = row.get("choice")
    if value not in allowed:
        raise ValueError(f"TypeSafe returned an unknown {name}: {value!r}")
    return value, _unit_interval(row.get("confidence"), f"{name} confidence")


def parse_answers(
    response: Mapping[str, Any], choice_to_url: Mapping[str, str] | None
) -> dict[str, Any]:
    answers = response.get("answers")
    if not isinstance(answers, Mapping):
        raise TypeError("TypeSafe response omitted answers")
    intent, confidence = _choice(answers, "intent", list(INTENTS))
    result: dict[str, Any] = {"intent": intent, "confidence": round(confidence, 3)}
    if choice_to_url:
        page, page_confidence = _choice(answers, "best_page", [*choice_to_url, NO_PAGE])
        result["best_page"] = choice_to_url.get(page)
        result["best_page_confidence"] = round(page_confidence, 3)
    return result


def classify_queries(
    queries: Sequence[str],
    *,
    site: str,
    brand_terms: Sequence[str] = (),
    pages: Sequence[Mapping[str, str]] = (),
    api_key: str | None = None,
    post: Poster | None = None,
) -> list[dict[str, Any]]:
    """Label each query; a failed query is reported, never allowed to sink the batch."""
    if len(pages) > MAX_PAGES:
        raise ValueError(f"At most {MAX_PAGES} pages can be offered as candidates.")
    key = api_key or load_api_key()
    send = post or _post_json
    page_criteria, choice_to_url = _page_criteria(pages) if pages else (None, None)

    def one(query: str) -> dict[str, Any]:
        try:
            response = send(build_payload(query, site, brand_terms, page_criteria), key)
            return {"query": query, **parse_answers(response, choice_to_url)}
        except Exception as exc:  # noqa: BLE001 - one bad answer must not lose the rest
            return {"query": query, "intent": None, "error": f"{type(exc).__name__}: {exc}"}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        return list(pool.map(one, queries))
