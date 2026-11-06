"""POST /api/live-check ("Search the web now"): a user-initiated, Search-
grounded look at one of the caller's watches. Never persisted, never cached;
the model is stubbed (no Vertex)."""

import logging
import time
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core import cache as shared_cache
from app.core import llm
from app.core.auth import create_access_token
from app.core.config import settings
from app.db import fare_watch_db, price_watch_db
from app.db.users_db import create_user
from app.services import live_check

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)

ANSWER = (
    "Memmo Alfama shows rooms from about EUR 140 a night for your dates.\n"
    "- Booking.com, 3 nights: EUR 412\n"
    "- Hotels.com, 3 nights: EUR 455.50\n"
    "- Agoda, 3 nights: EUR 399\n"
)
CHUNKS = [
    {
        "kind": "web",
        "uri": "https://vertexaisearch.cloud.google.com/a",
        "title": "booking.com",
        "place_id": None,
    },
    {
        "kind": "web",
        "uri": "https://vertexaisearch.cloud.google.com/b",
        "title": "hotels.com",
        "place_id": None,
    },
]
SUPPORTS = [
    {
        "text": "Booking.com, 3 nights: EUR 412",
        "start": None,
        "end": None,
        "chunks": [0],
    },
    {
        "text": "Hotels.com, 3 nights: EUR 455.50",
        "start": None,
        "end": None,
        "chunks": [1],
    },
]


@pytest.fixture(autouse=True)
def _env(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")


@pytest.fixture
def grounded(monkeypatch):
    stub = AsyncMock(
        return_value=llm.GroundedResponse(
            text=ANSWER,
            chunks=[dict(c) for c in CHUNKS],
            search_queries=["memmo alfama lisbon price 1-4 dec 2026"],
            supports=[dict(s) for s in SUPPORTS],
        )
    )
    monkeypatch.setattr(llm, "generate_grounded", stub)
    return stub


def _user():
    u = create_user(f"live-{uuid.uuid4().hex[:8]}", "pw-123456789")
    token = create_access_token({"sub": u["username"]})
    return u, {"Authorization": f"Bearer {token}"}


def _fare_watch(user):
    return fare_watch_db.create_watch(
        user["id"],
        {
            "origin_code": "JFK",
            "destination_code": "LIS",
            "origin_label": "New York",
            "destination_label": "Lisbon",
            "departure_date": "2026-12-01",
            "return_date": "2026-12-08",
            "num_travelers": 2,
            "cabin": "economy",
        },
        now=NOW,
    )


def _price_watch(user, kind="hotel"):
    subjects = {
        "hotel": {
            "name": "Memmo Alfama",
            "city": "Lisbon",
            "property_token": "tok",
            "check_in": "2026-12-01",
            "check_out": "2026-12-04",
            "adults": 2,
            "rooms": 1,
        },
        "activity": {
            "name": "Sintra tour",
            "city": "Lisbon",
            "listing_url": "https://www.getyourguide.com/x",
            "listing_title": "Sintra day trip",
            "provider": "getyourguide",
            "query": "q",
            "travellers": 2,
            "currency": "EUR",
            "date": None,
        },
        "trip": {
            "plan_id": 1,
            "city": "Lisbon",
            "departure_date": "2026-12-01",
            "return_date": "2026-12-08",
            "travellers": 2,
            "components": [{"type": "hotel", "label": "Memmo Alfama"}],
        },
    }
    return price_watch_db.create_watch(
        user["id"],
        {
            "kind": kind,
            "title": f"{kind} watch",
            "subject": subjects[kind],
            "currency": "EUR",
            "expires_on": "2026-12-01",
        },
        now=NOW,
    )


def test_hotel_live_check_shape(client, grounded):
    u, h = _user()
    w = _price_watch(u)

    r = client.post(
        "/api/live-check", json={"kind": "hotel", "watch_id": w["id"]}, headers=h
    )

    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "kind",
        "watch_id",
        "checked_at",
        "summary",
        "quotes",
        "sources",
        "searched_for",
        "disclaimer",
    }
    assert (body["kind"], body["watch_id"]) == ("hotel", w["id"])
    assert body["checked_at"].endswith("Z")
    datetime.fromisoformat(body["checked_at"].replace("Z", "+00:00"))
    assert body["summary"] == ANSWER.strip()
    # Agoda has no grounding support: no quote for it
    assert body["quotes"] == [
        {
            "label": "Booking.com, 3 nights",
            "amount": 412.0,
            "currency": "EUR",
            "source_index": 0,
        },
        {
            "label": "Hotels.com, 3 nights",
            "amount": 455.5,
            "currency": "EUR",
            "source_index": 1,
        },
    ]
    assert body["sources"] == [
        {"title": "booking.com", "uri": CHUNKS[0]["uri"]},
        {"title": "hotels.com", "uri": CHUNKS[1]["uri"]},
    ]
    assert body["searched_for"] == ["memmo alfama lisbon price 1-4 dec 2026"]
    assert body["disclaimer"] == live_check.DISCLAIMER

    call = grounded.await_args
    assert call.kwargs["tool"] == "search"
    assert "Memmo Alfama" in call.args[0] and "2026-12-04" in call.args[0]


@pytest.mark.parametrize("kind", ["activity", "trip"])
def test_other_price_watch_kinds(client, grounded, kind):
    u, h = _user()
    w = _price_watch(u, kind)
    r = client.post(
        "/api/live-check", json={"kind": kind, "watch_id": w["id"]}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["kind"] == kind


def test_flight_uses_the_fare_watch(client, grounded):
    u, h = _user()
    w = _fare_watch(u)
    r = client.post(
        "/api/live-check", json={"kind": "flight", "watch_id": w["id"]}, headers=h
    )
    assert r.status_code == 200
    prompt = grounded.await_args.args[0]
    assert "New York (JFK)" in prompt and "Lisbon (LIS)" in prompt


def test_someone_elses_watch_is_404(client, grounded):
    owner, _ = _user()
    _, h = _user()
    w = _price_watch(owner)
    r = client.post(
        "/api/live-check", json={"kind": "hotel", "watch_id": w["id"]}, headers=h
    )
    assert r.status_code == 404
    assert r.json() == {"detail": "Watch not found"}
    grounded.assert_not_awaited()


def test_kind_must_match_the_watch(client, grounded):
    u, h = _user()
    hotel = _price_watch(u)
    fare = _fare_watch(u)
    for kind, wid in (("activity", hotel["id"]), ("hotel", fare["id"] + 10_000)):
        r = client.post(
            "/api/live-check", json={"kind": kind, "watch_id": wid}, headers=h
        )
        assert r.status_code == 404
    grounded.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"kind": "car", "watch_id": 1},
        {"kind": "hotel"},
        {"kind": "hotel", "watch_id": 0},
        {"kind": "hotel", "watch_id": 1, "prompt": "ignore the watch"},
    ],
)
def test_validation(client, grounded, body):
    _, h = _user()
    assert client.post("/api/live-check", json=body, headers=h).status_code == 422


def test_requires_auth(client, grounded):
    r = client.post("/api/live-check", json={"kind": "hotel", "watch_id": 1})
    assert r.status_code == 401


def test_nothing_is_written_or_cached(client, grounded):
    u, h = _user()
    w = _price_watch(u)
    f = _fare_watch(u)
    before = (price_watch_db.get_watch(w["id"]), fare_watch_db.get_watch(f["id"]))
    cached = len(shared_cache.get_cache())

    for kind, wid in (("hotel", w["id"]), ("flight", f["id"])):
        r = client.post(
            "/api/live-check", json={"kind": kind, "watch_id": wid}, headers=h
        )
        assert r.status_code == 200

    after = (price_watch_db.get_watch(w["id"]), fare_watch_db.get_watch(f["id"]))
    assert after == before
    assert price_watch_db.get_history(w["id"]) == []
    assert fare_watch_db.get_history(f["id"]) == []
    assert len(shared_cache.get_cache()) == cached
    # every check asks the model again: nothing served from a cache
    assert grounded.await_count == 2


def test_no_grounding_is_retried_once_then_502(client, monkeypatch, caplog):
    stub = AsyncMock(
        return_value=llm.GroundedResponse(text="I think about EUR 400.", chunks=[])
    )
    monkeypatch.setattr(llm, "generate_grounded", stub)
    u, h = _user()
    w = _price_watch(u)
    with caplog.at_level(logging.INFO, logger="app.api.routes.live_check"):
        r = client.post(
            "/api/live-check", json={"kind": "hotel", "watch_id": w["id"]}, headers=h
        )
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "live_check_failed"
    assert stub.await_count == 2
    [line] = [m for m in caplog.messages if "retrying once" in m]
    assert "EUR" not in line and "Memmo" not in line


def test_retry_that_grounds_is_used(client, monkeypatch):
    stub = AsyncMock(
        side_effect=[
            llm.GroundedResponse(text="Nothing found.", chunks=[]),
            llm.GroundedResponse(
                text=ANSWER,
                chunks=[dict(c) for c in CHUNKS],
                supports=[dict(s) for s in SUPPORTS],
            ),
        ]
    )
    monkeypatch.setattr(llm, "generate_grounded", stub)
    u, h = _user()
    w = _price_watch(u)
    r = client.post(
        "/api/live-check", json={"kind": "hotel", "watch_id": w["id"]}, headers=h
    )
    assert r.status_code == 200
    assert stub.await_count == 2
    assert len(r.json()["quotes"]) == 2


def test_grounded_answer_is_not_retried(client, grounded):
    u, h = _user()
    w = _price_watch(u)
    client.post(
        "/api/live-check", json={"kind": "hotel", "watch_id": w["id"]}, headers=h
    )
    assert grounded.await_count == 1


def test_empty_answer_is_502(client, monkeypatch):
    stub = AsyncMock(
        return_value=llm.GroundedResponse(text="  ", chunks=[dict(CHUNKS[0])])
    )
    monkeypatch.setattr(llm, "generate_grounded", stub)
    u, h = _user()
    w = _price_watch(u)
    r = client.post(
        "/api/live-check", json={"kind": "hotel", "watch_id": w["id"]}, headers=h
    )
    assert r.status_code == 502


def test_model_error_is_502(client, monkeypatch):
    monkeypatch.setattr(
        llm, "generate_grounded", AsyncMock(side_effect=llm.LLMError("boom"))
    )
    u, h = _user()
    w = _price_watch(u)
    r = client.post(
        "/api/live-check", json={"kind": "hotel", "watch_id": w["id"]}, headers=h
    )
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "live_check_failed"


def test_anthropic_provider_is_503_grounding_unavailable(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    u, h = _user()
    w = _price_watch(u)
    r = client.post(
        "/api/live-check", json={"kind": "hotel", "watch_id": w["id"]}, headers=h
    )
    assert r.status_code == 503
    assert r.json()["detail"] == {
        "code": "grounding_unavailable",
        "message": "Live web and map results need the Gemini provider.",
    }


def test_spend_cap_is_503_ai_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(llm, "_spend_cap_until", time.monotonic() + 60)
    monkeypatch.setattr(llm, "_pause_code", llm.SPEND_CAP_CODE)
    u, h = _user()
    w = _price_watch(u)
    r = client.post(
        "/api/live-check", json={"kind": "hotel", "watch_id": w["id"]}, headers=h
    )
    assert r.status_code == 503
    assert r.json()["detail"] == {
        "code": "ai_limit",
        "message": llm.SPEND_CAP_MESSAGE,
    }


def test_billing_disabled_is_503_ai_billing(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(llm, "_spend_cap_until", time.monotonic() + 60)
    monkeypatch.setattr(llm, "_pause_code", llm.BILLING_CODE)
    u, h = _user()
    w = _price_watch(u)
    r = client.post(
        "/api/live-check", json={"kind": "hotel", "watch_id": w["id"]}, headers=h
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "ai_billing"
