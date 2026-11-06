"""Near Me v2 (``sections: true``): one Maps-grounded Gemini call, four
sections, items only from Maps grounding chunks, never cached. v1 (no
``sections``) is covered by test_nearby.py and must stay unchanged."""

import logging
import time
import uuid
from unittest.mock import AsyncMock

import pytest

from app.agents.activities_agent import ActivitiesAgent
from app.api.routes import nearby
from app.core import cache as shared_cache
from app.core import llm
from app.core.auth import create_access_token
from app.core.config import settings
from app.db.users_db import create_user

LISBON = {"lat": 38.7223, "lng": -9.1393}
V2 = {**LISBON, "sections": True}


def _maps(i, title):
    return {
        "kind": "maps",
        "uri": f"https://maps.google.com/?cid={i}",
        # as Vertex returns them
        "title": f"{title} - Google Maps",
        "place_id": f"places/ChIJ{i}",
    }


CHUNKS = [
    _maps(1, "Castelo de São Jorge"),
    _maps(2, "Time Out Market Lisboa"),
    _maps(3, "A Vida Portuguesa"),
    _maps(4, "Memmo Alfama Hotel"),
    *[_maps(10 + i, f"Tasca Number {i}") for i in range(12)],
]
TEXT = "\n".join(
    [
        "## See",
        "* Castelo de São Jorge - Moorish castle",
        "* Imaginary Tower - not on Maps",
        "## Eat",
        "* Time Out Market - Food hall",
        *[f"* Tasca Number {i} - Petiscos" for i in range(12)],
        "## Shop",
        "* A Vida Portuguesa - Heritage brands",
        "## Stay",
        "* Memmo Alfama Hotel - Rooftop pool",
    ]
)
SUPPORTS = [
    {"text": "Castelo de São Jorge", "start": None, "end": None, "chunks": [0]},
    {"text": "Memmo Alfama Hotel", "start": None, "end": None, "chunks": [3]},
]


@pytest.fixture(autouse=True)
def _env(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    nearby._cache.clear()
    yield
    nearby._cache.clear()


@pytest.fixture
def grounded(monkeypatch):
    stub = AsyncMock(
        return_value=llm.GroundedResponse(
            text=TEXT,
            chunks=[dict(c) for c in CHUNKS],
            supports=[dict(x) for x in SUPPORTS],
        )
    )
    monkeypatch.setattr(llm, "generate_grounded", stub)
    return stub


@pytest.fixture
def no_agent(monkeypatch):
    run = AsyncMock(side_effect=AssertionError("v2 must not run the agent"))
    monkeypatch.setattr(ActivitiesAgent, "run", run)
    return run


def _headers():
    u = create_user(f"near2-{uuid.uuid4().hex[:8]}", "pw-123456789")
    return {"Authorization": f"Bearer {create_access_token({'sub': u['username']})}"}


def test_v2_shape(client, grounded, no_agent):
    r = client.post("/api/nearby", json=V2, headers=_headers())

    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"place", "sections", "attribution", "sources"}
    assert body["place"]["name"] == "Lisbon"
    assert body["place"]["country_code"] == "PT"
    assert body["attribution"] == "Google Maps"
    assert [s["id"] for s in body["sections"]] == ["see", "eat", "shop", "stay"]
    see, eat, shop, stay = (s["items"] for s in body["sections"])
    assert see == [
        {
            "name": "Castelo de São Jorge",
            "summary": "Moorish castle",
            "maps_uri": "https://maps.google.com/?cid=1",
            "place_id": "ChIJ1",
            "category": "see",
        }
    ]
    # the default limit is 6 per section
    assert len(eat) == 6 and eat[0]["name"] == "Time Out Market Lisboa"
    assert [i["name"] for i in shop] == ["A Vida Portuguesa"]
    assert [i["name"] for i in stay] == ["Memmo Alfama Hotel"]
    assert body["sources"][0] == {
        "title": "Castelo de São Jorge",
        "uri": "https://maps.google.com/?cid=1",
    }
    assert all(set(s) == {"title", "uri"} for s in body["sources"])


def test_v2_call_is_maps_grounded_at_the_users_location(client, grounded):
    body = {**V2, "language": "pt-PT", "limit": 3, "interests": ["azulejos"]}
    client.post("/api/nearby", json=body, headers=_headers())

    [call] = grounded.await_args_list
    prompt = call.args[0]
    kw = call.kwargs
    assert kw["tool"] == "maps"
    assert (kw["lat"], kw["lng"]) == (LISBON["lat"], LISBON["lng"])
    assert kw["language"] == "pt-PT"
    assert "Lisbon" in prompt and "up to 3" in prompt and "azulejos" in prompt
    assert "Today is" in kw["system"]


def test_v2_language_defaults_to_english(client, grounded):
    client.post("/api/nearby", json=V2, headers=_headers())
    assert grounded.await_args.kwargs["language"] == "en"


def test_v2_limit_per_section(client, grounded):
    r = client.post("/api/nearby", json={**V2, "limit": 2}, headers=_headers())
    assert [len(s["items"]) for s in r.json()["sections"]] == [1, 2, 1, 1]


@pytest.mark.parametrize("limit", [0, 11, 20])
def test_v2_limit_bounds(client, grounded, limit):
    r = client.post("/api/nearby", json={**V2, "limit": limit}, headers=_headers())
    assert r.status_code == 422
    grounded.assert_not_awaited()


@pytest.mark.parametrize("language", ["", "english language", "e" * 40, "en_US;"])
def test_v2_language_validation(client, grounded, language):
    r = client.post(
        "/api/nearby", json={**V2, "language": language}, headers=_headers()
    )
    assert r.status_code == 422


def test_v1_still_accepts_limits_up_to_20(client, monkeypatch):
    run = AsyncMock(return_value={"results": [{"name": str(i)} for i in range(30)]})
    monkeypatch.setattr(ActivitiesAgent, "run", run)
    r = client.post("/api/nearby", json={**LISBON, "limit": 20}, headers=_headers())
    assert r.status_code == 200
    assert set(r.json()) == {"place", "items"}
    assert len(r.json()["items"]) == 20


def test_v1_with_sections_false_is_v1(client, monkeypatch, grounded):
    run = AsyncMock(return_value={"results": [{"name": "x"}]})
    monkeypatch.setattr(ActivitiesAgent, "run", run)
    r = client.post(
        "/api/nearby", json={**LISBON, "sections": False}, headers=_headers()
    )
    assert r.json()["items"] == [{"name": "x"}]
    grounded.assert_not_awaited()


def test_ungrounded_answer_is_retried_once_then_empty(client, monkeypatch, caplog):
    stub = AsyncMock(
        return_value=llm.GroundedResponse(text="## See\n* Made Up Place - x", chunks=[])
    )
    monkeypatch.setattr(llm, "generate_grounded", stub)
    with caplog.at_level(logging.INFO, logger="app.api.routes.nearby"):
        r = client.post("/api/nearby", json=V2, headers=_headers())
    assert r.status_code == 200
    assert [s["items"] for s in r.json()["sections"]] == [[], [], [], []]
    assert r.json()["sources"] == []
    assert stub.await_count == 2
    assert any("retrying once" in m for m in caplog.messages)


def test_retry_that_grounds_is_used(client, monkeypatch):
    stub = AsyncMock(
        side_effect=[
            llm.GroundedResponse(text="## See\n* x - y", chunks=[]),
            llm.GroundedResponse(text=TEXT, chunks=[dict(c) for c in CHUNKS]),
        ]
    )
    monkeypatch.setattr(llm, "generate_grounded", stub)
    r = client.post("/api/nearby", json=V2, headers=_headers())
    assert stub.await_count == 2
    assert r.json()["sections"][0]["items"][0]["name"] == "Castelo de São Jorge"


def test_grounded_answer_is_not_retried(client, grounded):
    client.post("/api/nearby", json=V2, headers=_headers())
    assert grounded.await_count == 1


def test_v2_is_never_cached(client, grounded):
    h = _headers()
    before = len(shared_cache.get_cache())
    client.post("/api/nearby", json=V2, headers=h)
    client.post("/api/nearby", json=V2, headers=h)
    assert grounded.await_count == 2
    assert len(nearby._cache) == 0
    assert len(shared_cache.get_cache()) == before


def test_v2_no_place_is_404(client, grounded):
    r = client.post(
        "/api/nearby", json={"lat": 0, "lng": -30, "sections": True}, headers=_headers()
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "no_place"
    grounded.assert_not_awaited()


def test_v2_on_anthropic_is_503_grounding_unavailable(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    r = client.post("/api/nearby", json=V2, headers=_headers())
    assert r.status_code == 503
    assert r.json()["detail"] == {
        "code": "grounding_unavailable",
        "message": "Live web and map results need the Gemini provider.",
    }


def test_v1_on_anthropic_is_unaffected(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    run = AsyncMock(return_value={"results": [{"name": "x"}]})
    monkeypatch.setattr(ActivitiesAgent, "run", run)
    r = client.post("/api/nearby", json=LISBON, headers=_headers())
    assert r.status_code == 200


def test_v2_spend_cap_is_503_ai_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(llm, "_spend_cap_until", time.monotonic() + 60)
    monkeypatch.setattr(llm, "_pause_code", llm.SPEND_CAP_CODE)
    r = client.post("/api/nearby", json=V2, headers=_headers())
    assert r.status_code == 503
    assert r.json()["detail"] == {
        "code": "ai_limit",
        "message": llm.SPEND_CAP_MESSAGE,
    }


def test_v2_billing_is_503_ai_billing(client, monkeypatch):
    stub = AsyncMock(
        side_effect=llm.LLMError(llm.BILLING_MESSAGE, user_code=llm.BILLING_CODE)
    )
    monkeypatch.setattr(llm, "generate_grounded", stub)
    r = client.post("/api/nearby", json=V2, headers=_headers())
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "ai_billing"


def test_v2_model_failure_is_502_agent_error(client, monkeypatch):
    stub = AsyncMock(side_effect=llm.LLMError("boom", retryable=True))
    monkeypatch.setattr(llm, "generate_grounded", stub)
    r = client.post("/api/nearby", json=V2, headers=_headers())
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "agent_error"


def test_v2_requires_auth(client, grounded):
    assert client.post("/api/nearby", json=V2).status_code == 401
