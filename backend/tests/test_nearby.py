"""Near me: nearest known place from the local places table, then the
existing activities agent for it (mocked: no LLM), cached per ~5 km cell."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.agents.activities_agent import ActivitiesAgent
from app.api.routes import nearby
from app.core.auth import create_access_token
from app.db.places_db import nearest_place
from app.db.preferences_db import save_preferences
from app.db.users_db import create_user

KYOTO = {"lat": 35.02107, "lng": 135.75385}
ITEMS = [
    {"name": f"Activity {i}", "category": "culture", "similarity_score": 0.9}
    for i in range(12)
]


@pytest.fixture(autouse=True)
def _env(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    nearby._cache.clear()
    yield
    nearby._cache.clear()


@pytest.fixture
def agent(monkeypatch):
    run = AsyncMock(return_value={"results": [dict(i) for i in ITEMS]})
    monkeypatch.setattr(ActivitiesAgent, "run", run)
    return run


def _user():
    u = create_user(f"near-{uuid.uuid4().hex[:8]}", "pw-123456789")
    token = create_access_token({"sub": u["username"]})
    return u, {"Authorization": f"Bearer {token}"}


# ── Nearest place ─────────────────────────────────────────────────────────────


def test_nearest_place_finds_the_city():
    p = nearest_place(35.03, 135.76)
    assert p["name"] == "Kyoto"
    assert p["country"] == "Japan"
    assert p["distance_km"] < 3


def test_same_name_towns_are_told_apart_by_region():
    maine = nearest_place(43.66, -70.26)
    oregon = nearest_place(45.52, -122.68)
    assert (maine["name"], maine["region"]) == ("Portland", "Maine")
    assert (oregon["name"], oregon["region"]) == ("Portland", "Oregon")
    assert maine["country"] == oregon["country"] == "United States"


def test_nearest_place_none_in_open_ocean():
    assert nearest_place(0.0, -30.0) is None


def test_nearest_place_respects_the_radius():
    assert nearest_place(35.03, 135.76, max_km=0.001) is None


def test_nearest_place_across_the_antimeridian():
    # Savusavu, Fiji (179.34° E) is ~72 km from a point just west of 180° W
    p = nearest_place(-16.78, -179.99)
    assert p["name"] == "Savusavu"
    assert p["distance_km"] <= 75


# ── Route ─────────────────────────────────────────────────────────────────────


def test_nearby_requires_auth(client):
    assert client.post("/api/nearby", json=KYOTO).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"lat": 91, "lng": 0},
        {"lat": 0, "lng": -181},
        {**KYOTO, "limit": 0},
        {**KYOTO, "limit": 21},
        {"lat": 10},
    ],
)
def test_nearby_validation(client, body):
    _, h = _user()
    assert client.post("/api/nearby", json=body, headers=h).status_code == 422


def test_nearby_returns_place_and_items(client, agent):
    _, h = _user()
    r = client.post(
        "/api/nearby", json={**KYOTO, "interests": ["temples"], "limit": 3}, headers=h
    )
    assert r.status_code == 200
    body = r.json()
    assert body["place"]["name"] == "Kyoto"
    assert body["place"]["country"] == "Japan"
    assert body["place"]["lat"] == pytest.approx(35.02107)
    assert body["place"]["distance_km"] == 0
    assert body["place"]["region"] == "Kyoto"
    assert body["items"] == ITEMS[:3]
    req = agent.await_args.args[0]
    # the region repeats the city's name, so the label leaves it out
    assert req.destination == "Kyoto, Japan"
    assert req.interests == ["temples"]


def test_label_carries_the_region(client, agent):
    _, h = _user()
    r = client.post("/api/nearby", json={"lat": 43.66, "lng": -70.26}, headers=h)
    assert r.json()["place"]["region"] == "Maine"
    assert agent.await_args.args[0].destination == "Portland, Maine, United States"


def test_interests_are_trimmed_and_bounded(client, agent):
    _, h = _user()
    body = {**KYOTO, "interests": ["  art ", "food"]}
    assert client.post("/api/nearby", json=body, headers=h).status_code == 200
    assert agent.await_args.args[0].interests == ["art", "food"]
    for bad in ([""], ["   "], ["x" * 61]):
        r = client.post("/api/nearby", json={**KYOTO, "interests": bad}, headers=h)
        assert r.status_code == 422


def test_taste_profiles_never_share_a_cache_entry(client, agent, monkeypatch):
    taste = {"value": "likes ramen"}
    monkeypatch.setattr(nearby, "derive_taste_context", lambda u: taste["value"])
    _, h = _user()
    client.post("/api/nearby", json=KYOTO, headers=h)
    taste["value"] = "likes museums"
    client.post("/api/nearby", json=KYOTO, headers=h)
    assert agent.await_count == 2


def test_default_limit_is_eight(client, agent):
    _, h = _user()
    body = client.post("/api/nearby", json=KYOTO, headers=h).json()
    assert len(body["items"]) == 8


def test_interests_fall_back_to_saved_preferences(client, agent):
    u, h = _user()
    save_preferences(u["username"], {"interests": ["food", "markets"]})
    client.post("/api/nearby", json=KYOTO, headers=h)
    assert agent.await_args.args[0].interests == ["food", "markets"]


def test_taste_context_is_applied(client, agent, monkeypatch):
    monkeypatch.setattr(nearby, "derive_taste_context", lambda u: "likes ramen")
    _, h = _user()
    client.post("/api/nearby", json=KYOTO, headers=h)
    assert agent.await_args.args[0].taste_context == "likes ramen"


def test_cached_per_cell_and_interests(client, agent):
    _, h = _user()
    client.post("/api/nearby", json={**KYOTO, "interests": ["art"]}, headers=h)
    # ~1 km away: same 0.05° cell → served from the cache
    near = {"lat": 35.012, "lng": 135.752, "interests": ["art"]}
    assert client.post("/api/nearby", json=near, headers=h).status_code == 200
    assert agent.await_count == 1
    client.post("/api/nearby", json={**KYOTO, "interests": ["food"]}, headers=h)
    assert agent.await_count == 2


def test_no_place_is_404(client, agent):
    _, h = _user()
    r = client.post("/api/nearby", json={"lat": 0, "lng": -30}, headers=h)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "no_place"
    agent.assert_not_awaited()


def test_agent_error_is_502_and_not_cached(client, monkeypatch):
    run = AsyncMock(return_value={"error": "overloaded"})
    monkeypatch.setattr(ActivitiesAgent, "run", run)
    _, h = _user()
    r = client.post("/api/nearby", json=KYOTO, headers=h)
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "agent_error"
    client.post("/api/nearby", json=KYOTO, headers=h)
    assert run.await_count == 2
