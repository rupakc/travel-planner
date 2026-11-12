"""Stress-test route: plan_id progress join."""

import uuid

import pytest

from app.agents.stress_test_agent import StressTestAgent
from app.db import trip_prep_db

BODY = {
    "origin": "New York",
    "destination": "Tokyo, Japan",
    "departure_date": "2027-04-01",
    "return_date": "2027-04-08",
    "nationality": "American",
    "itinerary": {"days": []},
}


@pytest.fixture()
def trip(client, admin_headers):
    r = client.post(
        "/api/plans",
        json={
            "name": "ST",
            "search_data": {"destination": "Tokyo", "departure_date": "2027-04-01"},
            "selections": {"itinerary": {"days": [{"slots": [{"activity": "x"}]}]}},
        },
        headers=admin_headers,
    )
    return r.json()["id"]


@pytest.fixture()
def hook(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.game.trip_hooks.on_smart_planner",
        lambda uid, pid, score: calls.append((pid, score)),
    )
    return calls


def _stub(monkeypatch, result):
    async def run(self, *a, **k):
        return result

    monkeypatch.setattr(StressTestAgent, "run", run)


def _post(client, headers, plan_id, **extra):
    return client.post(
        "/api/stress-test", json={**BODY, "plan_id": plan_id, **extra}, headers=headers
    )


def test_improved_score_hooks_once_equal_does_not(
    client, admin_headers, trip, hook, monkeypatch
):
    _stub(monkeypatch, {"overall_score": 70, "issues": []})
    r = _post(client, admin_headers, trip)
    assert r.status_code == 200
    assert r.json() == {"overall_score": 70, "issues": []}
    assert hook == [(trip, 70)]
    assert trip_prep_db.get_meta(trip, "stress_test") == {"score": 70}
    assert trip_prep_db.get_state(trip)["stress_test"]["done"]
    _post(client, admin_headers, trip)
    assert hook == [(trip, 70)]
    _stub(monkeypatch, {"score": 85})
    _post(client, admin_headers, trip)
    assert hook == [(trip, 70), (trip, 85)]


def test_other_users_plan_ignored(client, trip, hook, monkeypatch):
    from app.core.auth import create_access_token
    from app.db.users_db import create_user

    u = create_user(f"st-{uuid.uuid4().hex[:8]}", "pw-123456789")
    h = {"Authorization": f"Bearer {create_access_token({'sub': u['username']})}"}
    _stub(monkeypatch, {"overall_score": 60})
    assert _post(client, h, trip).status_code == 200
    assert hook == []
    assert trip_prep_db.get_meta(trip, "stress_test") is None


def test_anonymous_no_write(client, trip, hook, monkeypatch):
    _stub(monkeypatch, {"overall_score": 60})
    assert _post(client, {}, trip).status_code == 200
    assert hook == [] and trip_prep_db.get_meta(trip, "stress_test") is None


def test_bad_score_ignored(client, admin_headers, trip, hook, monkeypatch):
    _stub(monkeypatch, {"overall_score": 140})
    assert _post(client, admin_headers, trip).status_code == 200
    assert hook == [] and trip_prep_db.get_meta(trip, "stress_test") is None


def test_hook_failure_swallowed(client, admin_headers, trip, monkeypatch):
    def boom(*a):
        raise RuntimeError("x")

    monkeypatch.setattr("app.game.trip_hooks.on_smart_planner", boom)
    _stub(monkeypatch, {"overall_score": 50})
    r = _post(client, admin_headers, trip)
    assert r.status_code == 200 and r.json() == {"overall_score": 50}
