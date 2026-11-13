"""GET story / POST advice routes: ownership, no network, 24 h cache."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from app.agents.pricing_advisor_agent import PricingAdvisorAgent
from app.core.auth import create_access_token
from app.core.config import settings
from app.db import alerts_db, fare_watch_db, price_watch_db
from app.db.database import get_connection
from app.db.users_db import create_user

NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _env(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    monkeypatch.setattr(settings, "serpapi_key", "test-key")
    with get_connection() as conn:
        conn.execute("DELETE FROM alert_advice")


def _user():
    u = create_user(f"st-{uuid.uuid4().hex[:8]}", "pw-123456789")
    return u, {"Authorization": f"Bearer {create_access_token({'sub': u['username']})}"}


def _flight(user, prices=(480.0, 455.0, 430.0)):
    w = fare_watch_db.create_watch(
        user["id"],
        {
            "origin_code": "BER",
            "destination_code": "LIS",
            "origin_label": "Berlin",
            "destination_label": "Lisbon",
            "departure_date": (NOW + timedelta(days=40)).date().isoformat(),
            "num_travelers": 1,
        },
        now=NOW,
    )
    for i, p in enumerate(prices):
        at = (NOW - timedelta(days=len(prices) - 1 - i)).isoformat()
        fare_watch_db.add_history(w["id"], {"checked_at": at, "price": p})
    with get_connection() as conn:
        conn.execute(
            "UPDATE fare_watches SET last_checked_at = ?, google_typical_low = 440,"
            " google_typical_high = 520 WHERE id = ?",
            (NOW.isoformat(), w["id"]),
        )
    return w


def _hotel(user):
    return price_watch_db.create_watch(
        user["id"],
        {
            "kind": "hotel",
            "title": "Hotel",
            "expires_on": (NOW + timedelta(days=30)).date().isoformat(),
            "currency": "USD",
        },
        now=NOW,
    )


def test_story_shape(client):
    u, h = _user()
    w = _flight(u)
    r = client.get(f"/api/alerts/watches/flight/{w['id']}/story", headers=h)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["kind"] == "flight" and s["watch_id"] == w["id"]
    assert [p["price"] for p in s["points"]] == [480.0, 455.0, 430.0]
    assert s["typical"]["source"] == "google" and s["live_prices"] is True
    assert s["advice"]["code"] == "at_lowest" and s["caught"] is None


def test_story_404_other_user(client):
    a, _ = _user()
    _, hb = _user()
    w = _flight(a)
    r = client.get(f"/api/alerts/watches/flight/{w['id']}/story", headers=hb)
    assert r.status_code == 404 and r.json()["error_code"] == "watch_not_found"


def test_story_kind_invalid_and_wrong_kind(client):
    u, h = _user()
    w = _hotel(u)
    assert client.get("/api/alerts/watches/boat/1/story", headers=h).status_code == 422
    r = client.get(f"/api/alerts/watches/activity/{w['id']}/story", headers=h)
    assert r.status_code == 404
    assert (
        client.get(f"/api/alerts/watches/hotel/{w['id']}/story", headers=h).status_code
        == 200
    )


def test_story_requires_auth(client):
    assert client.get("/api/alerts/watches/flight/1/story").status_code == 401


def test_story_makes_no_network_call(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network call")

    monkeypatch.setattr(httpx.AsyncClient, "send", boom)
    u, h = _user()
    w = _flight(u)
    assert (
        client.get(f"/api/alerts/watches/flight/{w['id']}/story", headers=h).status_code
        == 200
    )


def test_story_without_key_paused(client, monkeypatch):
    monkeypatch.setattr(settings, "serpapi_key", "")
    u, h = _user()
    w = _flight(u)
    with get_connection() as conn:
        conn.execute(
            "UPDATE fare_watches SET last_checked_at = ? WHERE id = ?",
            ((NOW - timedelta(days=9)).isoformat(), w["id"]),
        )
    s = client.get(f"/api/alerts/watches/flight/{w['id']}/story", headers=h).json()
    assert s["advice"] == {"code": "checks_paused", "params": {"days": 9}}
    assert s["verdict"] is None and s["live_prices"] is False


def test_caught_from_savings_rows(client):
    u, h = _user()
    w = _flight(u)
    alerts_db.insert_saving(
        {
            "user_id": u["id"], "watch_kind": "flight", "watch_id": w["id"],
            "notification_id": uuid.uuid4().int % 10**9, "from_price": 480.0, "to_price": 430.0,
            "baseline": 480.0, "currency": "USD", "target_hit": False,
        }
    )  # fmt: skip
    s = client.get(f"/api/alerts/watches/flight/{w['id']}/story", headers=h).json()
    assert s["caught"] == 50.0


def test_advice_flight_cached_24h(client, monkeypatch):
    run = AsyncMock(return_value={"recommendation_detail": "Book in about 6 weeks."})
    monkeypatch.setattr(PricingAdvisorAgent, "run", run)
    u, h = _user()
    w = _flight(u)
    url = f"/api/alerts/watches/flight/{w['id']}/advice"
    r1 = client.post(url, headers=h)
    assert r1.status_code == 200, r1.text
    assert r1.json()["tip"] == "Book in about 6 weeks."
    assert r1.json()["cached"] is False and r1.json()["source"] == "ai"
    r2 = client.post(url, headers=h)
    assert r2.json()["cached"] is True and r2.json()["tip"] == r1.json()["tip"]
    assert run.call_count == 1
    assert run.call_args.kwargs["avg_price"] == 480.0  # typical midpoint
    # an expired tip is regenerated
    alerts_db.put_advice(
        "flight",
        w["id"],
        "old",
        (NOW - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert client.post(url, headers=h).json()["cached"] is False
    assert run.call_count == 2


def test_advice_hotel_422(client, monkeypatch):
    monkeypatch.setattr(PricingAdvisorAgent, "run", AsyncMock())
    u, h = _user()
    w = _hotel(u)
    r = client.post(f"/api/alerts/watches/hotel/{w['id']}/advice", headers=h)
    assert r.status_code == 422 and r.json()["error_code"] == "advice_unsupported"


def test_advice_404_other_user(client):
    a, _ = _user()
    _, hb = _user()
    w = _flight(a)
    r = client.post(f"/api/alerts/watches/flight/{w['id']}/advice", headers=hb)
    assert r.status_code == 404


def test_advice_spend_cap_503(client, monkeypatch):
    monkeypatch.setattr(
        PricingAdvisorAgent,
        "run",
        AsyncMock(return_value={"error": "AI limit reached", "error_code": "ai_limit"}),
    )
    u, h = _user()
    w = _flight(u)
    r = client.post(f"/api/alerts/watches/flight/{w['id']}/advice", headers=h)
    assert r.status_code == 503 and r.json()["error_code"] == "ai_limit"
    assert alerts_db.get_advice("flight", w["id"]) is None


def test_advice_agent_failure_502(client, monkeypatch):
    monkeypatch.setattr(
        PricingAdvisorAgent, "run", AsyncMock(return_value={"error": "x"})
    )
    u, h = _user()
    w = _flight(u)
    r = client.post(f"/api/alerts/watches/flight/{w['id']}/advice", headers=h)
    assert r.status_code == 502 and r.json()["error_code"] == "advice_failed"


def test_advice_no_points_422_without_llm(client, monkeypatch):
    run = AsyncMock()
    monkeypatch.setattr(PricingAdvisorAgent, "run", run)
    u, h = _user()
    w = _flight(u, prices=())
    r = client.post(f"/api/alerts/watches/flight/{w['id']}/advice", headers=h)
    assert r.status_code == 422 and r.json()["error_code"] == "advice_no_data"
    run.assert_not_called()


def test_advice_billing_503(client, monkeypatch):
    monkeypatch.setattr(
        PricingAdvisorAgent,
        "run",
        AsyncMock(return_value={"error": "billing off", "error_code": "ai_billing"}),
    )
    u, h = _user()
    w = _flight(u)
    r = client.post(f"/api/alerts/watches/flight/{w['id']}/advice", headers=h)
    assert r.status_code == 503 and r.json()["error_code"] == "ai_billing"


def test_advice_cache_is_keyed_by_locale(client, monkeypatch):
    run = AsyncMock(return_value={"recommendation_detail": "tip"})
    monkeypatch.setattr(PricingAdvisorAgent, "run", run)
    u, h = _user()
    w = _flight(u)
    url = f"/api/alerts/watches/flight/{w['id']}/advice"
    assert client.post(url, headers=h).json()["cached"] is False
    assert client.post(url, headers=h).json()["cached"] is True
    from app.db import users_db

    with get_connection() as conn:
        conn.execute("UPDATE users SET locale = 'es' WHERE id = ?", (u["id"],))
    assert users_db.get_user_by_id(u["id"]).get("locale") == "es"
    assert (
        client.post(url, headers=h).json()["cached"] is False
    )  # English tip not reused
    assert client.post(url, headers=h).json()["cached"] is True
    assert run.call_count == 2
