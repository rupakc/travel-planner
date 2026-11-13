"""One-tap quick watch: pending rows, no live look at create, and the first
look (the baseline, never an alert). Live looks go to the fake SerpAPI."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.auth import create_access_token
from app.core.cache import get_cache
from app.core.config import settings
from app.db import alerts_db, fare_watch_db, notifications_db, price_watch_db
from app.db.database import get_connection
from app.db.users_db import create_user
from app.services import fare_watch, price_watch, serp_flights
from scripts import run_with_fake_serpapi

from .price_watch_fakes import FakeSource
from .test_fake_serpapi import fake  # noqa: F401  (fixture)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
LEGACY_FARE_KEYS = {
    "id", "plan_id", "origin_code", "destination_code", "departure_date",
    "return_date", "num_travelers", "alert_mode", "status", "baseline_price",
    "last_price", "lowest_price", "check_count", "next_check_at", "problem",
    "history", "booking_url", "email_enabled",
}  # fmt: skip
LEGACY_PRICE_KEYS = {
    "id", "kind", "title", "subtitle", "subject", "currency", "alert_mode",
    "status", "baseline_price", "last_price", "lowest_price", "check_count",
    "expires_on", "next_check_at", "problem", "history", "link",
    "already_below_target", "email_enabled",
}  # fmt: skip


@pytest.fixture(autouse=True)
def _env(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    monkeypatch.setattr(settings, "serpapi_key", "test-key")
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 200)
    monkeypatch.setattr(settings, "fare_watch_user_daily_share", 1.0)
    monkeypatch.setattr(settings, "fare_watch_max_active_per_user", 3)
    monkeypatch.setattr(fare_watch, "utcnow", lambda: NOW)
    monkeypatch.setattr(serp_flights, "_today", lambda: NOW.date())
    alerts_db.create_alert_tables()
    notifications_db.create_notifications_table()
    with get_connection() as conn:
        conn.execute("DELETE FROM fare_watch_quota")
        conn.execute("DELETE FROM fare_watch_user_quota")
    get_cache().clear()


@pytest.fixture
def src():
    s = FakeSource()
    s.kind = "hotel"  # the contract's kinds only: stand in for the hotel source
    old = price_watch.get_source("hotel")
    price_watch.register_source(s)
    yield s
    price_watch.unregister_source("hotel")
    if old is not None:
        price_watch.register_source(old)


def _user():
    u = create_user(f"qw-{uuid.uuid4().hex[:8]}", "pw-123456789")
    return u, {"Authorization": f"Bearer {create_access_token({'sub': u['username']})}"}


def _body(kind="hotel", **over):
    spec = {"name": "Lumen Hotel", "price": 400.0}
    body = {"kind": kind, "title": "Lumen Hotel", "spec": spec, "surface": "results"}
    body.update(over)
    return body


def _flight(**over):
    spec = {
        "origin": "LIS",
        "destination": "JFK",
        "departure_date": "2026-12-01",
        "return_date": "2026-12-08",
        "num_travelers": 1,
    }
    spec.update(over)
    return _body("flight", title="Lisbon to New York", spec=spec)


def _post(client, h, body):
    return client.post("/api/alerts/quick-watch", json=body, headers=h)


@pytest.fixture
def fake_serp(fake, monkeypatch):  # noqa: F811
    base, _ = fake()
    run_with_fake_serpapi.patch(f"{base}/search.json")
    yield base
    run_with_fake_serpapi.patch("https://serpapi.com/search")


def _calls(base):
    return httpx.get(f"{base}/__calls").json()["total"]


def test_quick_watch_makes_no_serpapi_call(client, src, fake_serp):
    _, h = _user()
    r = _post(client, h, _flight())
    assert r.status_code == 201, r.text
    w = r.json()
    assert w["kind"] == "flight" and w["existing"] is False
    assert w["watch"]["pending_first_check"] is True
    assert w["watch"]["alert_mode"] == "any_drop" and not w["watch"]["email_enabled"]
    assert w["watch"]["last_price"] is None and w["watch"]["next_check_at"]
    r = _post(client, h, _body())
    assert r.status_code == 201, r.text
    assert r.json()["watch"]["pending_first_check"] is True
    assert src.created == [] and _calls(fake_serp) == 0


def test_quick_watch_503_without_key(client, monkeypatch):
    monkeypatch.setattr(settings, "serpapi_key", "")
    _, h = _user()
    r = _post(client, h, _flight())
    assert r.status_code == 503 and r.json()["error_code"] == "live_prices_off"


def test_quick_watch_twice_returns_existing(client, src):
    u, h = _user()
    first = _post(client, h, _body()).json()
    second = _post(client, h, _body())
    assert second.status_code == 200
    assert second.json()["existing"] is True
    assert second.json()["watch"]["id"] == first["watch"]["id"]
    f1 = _post(client, h, _flight())
    f2 = _post(client, h, _flight())
    assert (f1.status_code, f2.status_code) == (201, 200)
    assert f2.json()["watch"]["id"] == f1.json()["watch"]["id"]
    assert len(price_watch_db.list_watches(u["id"])) == 1
    assert len(fare_watch_db.list_watches(u["id"])) == 1


def test_quick_watch_counts_toward_limit_409(client, src):
    _, h = _user()
    for n in range(3):
        assert _post(client, h, _body(spec={"name": f"H{n}"})).status_code == 201
    r = _post(client, h, _flight())
    assert r.status_code == 409 and r.json()["error_code"] == "watch_limit"
    assert r.json()["detail"] == price_watch.limit_message()
    # an already-watched subject still answers 200, over the limit
    assert _post(client, h, _body(spec={"name": "H0"})).status_code == 200


def test_bad_spec_422(client, src):
    _, h = _user()
    r = _post(client, h, _body(spec={}))
    assert r.status_code == 422 and r.json()["error_code"] == "spec_invalid"
    r = _post(client, h, _flight(origin=None))
    assert r.status_code == 422 and r.json()["error_code"] == "spec_invalid"
    r = _post(client, h, _body("trip", spec={}))
    assert r.status_code == 422 and r.json()["error_code"] == "spec_invalid"
    r = _post(client, h, _body("trip", spec={"plan_id": 999999}))
    assert r.status_code == 404 and r.json()["error_code"] == "trip_not_found"


def test_pending_watch_keeps_legacy_shape(client, src):
    _, h = _user()
    _post(client, h, _flight())
    _post(client, h, _body())
    fares = client.get("/api/fare-watches", headers=h).json()
    prices = client.get("/api/price-watches", headers=h).json()
    assert LEGACY_FARE_KEYS <= set(fares[0]) and fares[0]["last_price"] is None
    assert LEGACY_PRICE_KEYS <= set(prices[0]) and prices[0]["last_price"] is None
    assert fares[0]["pending_first_check"] is True
    assert prices[0]["pending_first_check"] is True
    assert prices[0]["already_below_target"] is False


@pytest.mark.asyncio
async def test_first_check_sets_baseline_no_alert(client, src, fake_serp):
    u, h = _user()
    _post(client, h, _flight())
    wid = fare_watch_db.list_watches(u["id"])[0]["id"]
    assert fare_watch_db.claim_watch(wid, NOW, NOW + fare_watch.LEASE)
    out = await fare_watch.check_watch(wid, now=NOW, api_key="k")
    w = fare_watch_db.get_watch(wid)
    assert out.status == "checked" and out.notification is None
    assert w["pending_first_check"] is False
    assert w["baseline_price"] and w["last_price"] == w["baseline_price"]
    assert w["check_count"] == 1 and _calls(fake_serp) > 0

    # price watch: the first look is the baseline; a later drop alerts
    _post(client, h, _body())
    pid = price_watch_db.list_watches(u["id"])[0]["id"]
    assert price_watch_db.claim_watch(pid, NOW, NOW + price_watch.LEASE)
    out = await price_watch.check_watch(pid, now=NOW, api_key="k")
    p = price_watch_db.get_watch(pid)
    assert out.status == "checked" and out.notification is None
    assert src.created[0]["spec"]["name"] == "Lumen Hotel"
    assert p["pending_first_check"] is False and p["baseline_price"] == 400.0
    assert p["subject"] == {"name": "Lumen Hotel", "token": "tok-1"}
    assert p["check_count"] == 1 and p["last_price"] == 400.0
    assert [x["price"] for x in price_watch_db.get_history(pid)] == [400.0]
    assert notifications_db.list_notifications(u["id"])["items"] == []
    later = NOW + timedelta(hours=13)
    src.queue.append(FakeSource_ok(300.0))
    price_watch_db.update_watch(pid, next_check_at=later.isoformat())
    price_watch_db.claim_watch(pid, later, later + price_watch.LEASE)
    out = await price_watch.check_watch(pid, now=later, api_key="k")
    assert out.notification and out.notification["kind"] == "hotel_drop"


def FakeSource_ok(price):
    from .price_watch_fakes import ok

    return ok(price)


@pytest.mark.asyncio
async def test_pending_hotel_unavailable_freezes_estimate(client, src):
    u, h = _user()
    r = _post(client, h, _body(spec={"name": "Ghost Inn", "no_match": True}))
    pid = r.json()["watch"]["id"]
    price_watch_db.claim_watch(pid, NOW, NOW + price_watch.LEASE)
    out = await price_watch.check_watch(pid, now=NOW, api_key="k")
    p = price_watch_db.get_watch(pid)
    assert out.status == "unavailable" and out.notification is None
    assert p["pending_first_check"] is False and p["unavailable_count"] == 1
    assert p["last_price"] is None and p["baseline_price"] is None
    assert p["last_observation"]["observed"]["estimate"] == {
        "price": 120.0,
        "source": "ai_estimate",
    }
    # still waiting for a live match: the next look retries the create
    assert price_watch.is_pending(p)
    assert notifications_db.list_notifications(u["id"])["items"] == []


def test_quick_watch_404_when_v2_off(client, monkeypatch):
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", False)
    _, h = _user()
    r = _post(client, h, _flight())
    assert r.status_code == 404 and r.json()["error_code"] == "alerts_v2_off"
