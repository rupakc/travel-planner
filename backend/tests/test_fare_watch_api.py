"""Fare watch + notifications API: auth, ownership, validation, check now,
unsubscribe links and the email field. SerpAPI `_call` is always mocked."""

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core import rate_limit
from app.core.auth import create_access_token
from app.core.cache import get_cache
from app.core.config import settings
from app.db import fare_watch_db, notifications_db
from app.db.database import get_connection
from app.db.users_db import _hash as real_hash
from app.db.users_db import create_user
from app.services import alert_email, fare_watch, serp_flights
from app.services.serp_flights import SerpAPIError

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)

TRIP = {
    "origin": "BER",
    "destination": "LIS",
    "departure_date": "2026-12-01",
    "return_date": "2026-12-08",
    "num_travelers": 2,
}


def _serp(prices, level="typical"):
    return {
        "best_flights": [{"price": p, "flights": [], "layovers": []} for p in prices],
        "other_flights": [],
        "price_insights": {
            "lowest_price": min(prices),
            "price_level": level,
            "typical_price_range": [450, 620],
        },
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch, client):
    # tokens are minted directly — skip bcrypt's deliberate slowness
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    monkeypatch.setattr(settings, "serpapi_key", "test-key")
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 200)
    monkeypatch.setattr(settings, "fare_watch_max_active_per_user", 10)
    monkeypatch.setattr(fare_watch, "utcnow", lambda: NOW)
    monkeypatch.setattr(serp_flights, "_today", lambda: NOW.date())
    monkeypatch.setattr(
        serp_flights, "_call", AsyncMock(return_value=_serp([480.0, 530.0]))
    )
    with get_connection() as conn:
        conn.execute("DELETE FROM fare_watch_quota")
    get_cache().clear()
    yield
    get_cache().clear()


def _user(email=None):
    u = create_user(f"fw-{uuid.uuid4().hex[:8]}", "pw-123456789", email=email)
    token = create_access_token({"sub": u["username"]})
    return u, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alice():
    return _user()


@pytest.fixture
def bob():
    return _user()


def _create(client, headers, **over):
    return client.post("/api/fare-watches", json={**TRIP, **over}, headers=headers)


# ── Create ────────────────────────────────────────────────────────────────────


def test_create_takes_the_baseline_inline(client, alice):
    _, h = alice
    r = _create(client, h)
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["already_watching"] is False
    assert w["origin_code"] == "BER"
    assert w["destination_code"] == "LIS"
    assert w["num_travelers"] == 2
    assert w["baseline_price"] == 480.0
    assert w["last_price"] == 480.0
    assert w["google_price_level"] == "typical"
    assert w["google_typical_low"] == 450
    assert w["status"] == "active"
    assert w["alert_mode"] == "any_drop"
    assert [p["price"] for p in w["history"]] == [480.0]
    assert w["booking_url"].startswith("https://www.google.com/flights#flt=BER.LIS.")
    assert "user_id" not in w and "lease_until" not in w
    assert serp_flights._call.call_count == 1


def test_create_after_a_search_reuses_cached_fares(client, alice):
    _, h = alice
    get_cache()[
        serp_flights._main_key("BER", "LIS", date(2026, 12, 1), date(2026, 12, 8), 2)
    ] = {"results": [{"price_usd": 455.0}], "price_insights": {"price_level": "low"}}
    w = _create(client, h).json()
    assert w["baseline_price"] == 455.0
    serp_flights._call.assert_not_called()


def test_create_resolves_typed_cities(client, alice):
    _, h = alice
    w = _create(client, h, origin="Berlin", destination="Lisbon").json()
    assert "BER" in w["origin_code"]
    assert "LIS" in w["destination_code"]
    assert w["origin_label"].startswith("Berlin")


def test_create_same_trip_returns_the_existing_watch(client, alice):
    _, h = alice
    first = _create(client, h).json()
    again = _create(client, h, alert_mode="below_target", target_price=400).json()
    assert again["id"] == first["id"]
    assert again["already_watching"] is True
    assert serp_flights._call.call_count == 1


def test_create_with_target(client, alice):
    _, h = alice
    w = _create(client, h, alert_mode="below_target", target_price=420).json()
    assert w["alert_mode"] == "below_target"
    assert w["target_price"] == 420


def test_target_mode_needs_a_target(client, alice):
    _, h = alice
    r = _create(client, h, alert_mode="below_target")
    assert r.status_code == 422


@pytest.mark.parametrize("flex", [1, 7, -3])
def test_flexible_days_is_zero_or_three(client, alice, flex):
    _, h = alice
    assert _create(client, h, flexible_days=flex).status_code == 422


def test_create_requires_auth(client):
    assert client.post("/api/fare-watches", json=TRIP).status_code == 401


def test_create_without_serpapi_is_503(client, alice, monkeypatch):
    monkeypatch.setattr(settings, "serpapi_key", "")
    r = _create(client, alice[1])
    assert r.status_code == 503
    assert "live" in r.json()["detail"].lower()


def test_multi_city_is_422(client, alice):
    r = _create(client, alice[1], destinations=["Paris", "Rome", "Lisbon"])
    assert r.status_code == 422
    assert r.json()["detail"] == (
        "Fare watch works for single-destination trips for now"
    )


def test_unresolvable_city_is_422(client, alice):
    r = _create(client, alice[1], destination="Qwxzv Nowhereville")
    assert r.status_code == 422
    assert "airport" in r.json()["detail"]


def test_past_departure_is_422(client, alice):
    r = _create(client, alice[1], departure_date="2026-11-04", return_date=None)
    assert r.status_code == 422


def test_return_before_departure_is_422(client, alice):
    r = _create(client, alice[1], return_date="2026-11-20")
    assert r.status_code == 422


def test_active_watch_limit(client, alice, monkeypatch):
    monkeypatch.setattr(settings, "fare_watch_max_active_per_user", 2)
    _, h = alice
    assert _create(client, h).status_code == 200
    assert _create(client, h, departure_date="2026-12-02").status_code == 200
    r = _create(client, h, departure_date="2026-12-03")
    assert r.status_code == 409
    assert "2 fares" in r.json()["detail"]


def test_create_from_a_saved_plan(client, alice):
    u, h = alice
    plan = client.post(
        "/api/plans",
        json={
            "name": "Lisbon",
            "search_data": {**TRIP, "nationality": "German"},
            "selections": {},
        },
        headers=h,
    ).json()
    r = client.post("/api/fare-watches", json={"plan_id": plan["id"]}, headers=h)
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["plan_id"] == plan["id"]
    assert w["departure_date"] == "2026-12-01"


def test_create_from_someone_elses_plan_is_404(client, alice, bob):
    plan = client.post(
        "/api/plans",
        json={"name": "x", "search_data": TRIP, "selections": {}},
        headers=bob[1],
    ).json()
    r = client.post("/api/fare-watches", json={"plan_id": plan["id"]}, headers=alice[1])
    assert r.status_code == 404


def test_create_when_budget_is_spent_schedules_the_baseline(client, alice, monkeypatch):
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 0)
    w = _create(client, alice[1]).json()
    assert w["baseline_price"] is None
    assert w["status"] == "active"
    assert w["next_check_at"] == NOW.isoformat()
    serp_flights._call.assert_not_called()


def test_create_survives_a_failed_baseline(client, alice):
    serp_flights._call.side_effect = SerpAPIError("timeout")
    r = _create(client, alice[1])
    assert r.status_code == 200
    assert r.json()["baseline_price"] is None
    assert r.json()["failure_count"] == 1


def test_email_needs_an_address_and_smtp(client, alice, monkeypatch):
    r = _create(client, alice[1], email_enabled=True)
    assert r.status_code == 422
    assert "email" in r.json()["detail"].lower()
    _, h = _user(email=f"{uuid.uuid4().hex[:6]}@example.com")
    assert _create(client, h, email_enabled=True).status_code == 422  # no SMTP
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    w = _create(client, h, email_enabled=True).json()
    assert w["email_enabled"] is True


# ── Read / match / ownership ──────────────────────────────────────────────────


def test_list_and_get_are_scoped_to_the_owner(client, alice, bob):
    w = _create(client, alice[1]).json()
    mine = client.get("/api/fare-watches", headers=alice[1]).json()
    assert [x["id"] for x in mine] == [w["id"]]
    assert client.get("/api/fare-watches", headers=bob[1]).json() == []
    assert (
        client.get(f"/api/fare-watches/{w['id']}", headers=alice[1]).status_code == 200
    )
    for method, path in (
        ("get", f"/api/fare-watches/{w['id']}"),
        ("patch", f"/api/fare-watches/{w['id']}"),
        ("delete", f"/api/fare-watches/{w['id']}"),
        ("post", f"/api/fare-watches/{w['id']}/check"),
    ):
        kwargs = {"json": {"status": "paused"}} if method == "patch" else {}
        r = getattr(client, method)(path, headers=bob[1], **kwargs)
        assert r.status_code == 404, (method, path)


def test_match_finds_the_watch_for_a_search(client, alice, bob):
    w = _create(client, alice[1]).json()
    r = client.post("/api/fare-watches/match", json=TRIP, headers=alice[1])
    assert r.json()["watch"]["id"] == w["id"]
    other = {**TRIP, "num_travelers": 3}
    assert client.post(
        "/api/fare-watches/match", json=other, headers=alice[1]
    ).json() == {"watch": None}
    assert client.post("/api/fare-watches/match", json=TRIP, headers=bob[1]).json() == {
        "watch": None
    }
    serp_flights._call.reset_mock()
    client.post("/api/fare-watches/match", json=TRIP, headers=alice[1])
    serp_flights._call.assert_not_called()


# ── Update / delete ───────────────────────────────────────────────────────────


def test_pause_and_resume(client, alice):
    _, h = alice
    w = _create(client, h).json()
    p = client.patch(
        f"/api/fare-watches/{w['id']}", json={"status": "paused"}, headers=h
    )
    assert p.json()["status"] == "paused"
    r = client.patch(
        f"/api/fare-watches/{w['id']}", json={"status": "active"}, headers=h
    )
    assert r.json()["status"] == "active"


def test_resume_from_error_retries_now(client, alice):
    _, h = alice
    w = _create(client, h).json()
    fare_watch_db.update_watch(
        w["id"], status="error", failure_count=3, last_error="boom"
    )
    r = client.patch(
        f"/api/fare-watches/{w['id']}", json={"status": "active"}, headers=h
    ).json()
    assert r["status"] == "active"
    assert r["failure_count"] == 0
    assert r["last_error"] is None
    assert r["next_check_at"] == NOW.isoformat()


def test_resume_respects_the_limit(client, alice, monkeypatch):
    _, h = alice
    w = _create(client, h).json()
    client.patch(f"/api/fare-watches/{w['id']}", json={"status": "paused"}, headers=h)
    _create(client, h, departure_date="2026-12-02")
    monkeypatch.setattr(settings, "fare_watch_max_active_per_user", 1)
    r = client.patch(
        f"/api/fare-watches/{w['id']}", json={"status": "active"}, headers=h
    )
    assert r.status_code == 409


def test_expired_watch_cannot_resume(client, alice):
    _, h = alice
    w = _create(client, h).json()
    fare_watch_db.update_watch(w["id"], status="expired")
    r = client.patch(
        f"/api/fare-watches/{w['id']}", json={"status": "active"}, headers=h
    )
    assert r.status_code == 409


def test_edit_mode_target_flex(client, alice):
    _, h = alice
    w = _create(client, h).json()
    r = client.patch(
        f"/api/fare-watches/{w['id']}",
        json={"alert_mode": "below_target", "target_price": 399, "flexible_days": 3},
        headers=h,
    ).json()
    assert (r["alert_mode"], r["target_price"], r["flexible_days"]) == (
        "below_target",
        399,
        3,
    )
    bad = client.patch(
        f"/api/fare-watches/{w['id']}", json={"target_price": -5}, headers=h
    )
    assert bad.status_code == 422


def test_switching_to_target_mode_needs_a_target(client, alice):
    _, h = alice
    w = _create(client, h).json()
    r = client.patch(
        f"/api/fare-watches/{w['id']}", json={"alert_mode": "below_target"}, headers=h
    )
    assert r.status_code == 422


def test_cannot_patch_scheduler_fields(client, alice):
    _, h = alice
    w = _create(client, h).json()
    client.patch(
        f"/api/fare-watches/{w['id']}",
        json={"baseline_price": 1, "status": "expired"},
        headers=h,
    )
    got = fare_watch_db.get_watch(w["id"])
    assert got["baseline_price"] == 480.0
    assert got["status"] == "active"


def test_delete(client, alice):
    _, h = alice
    w = _create(client, h).json()
    assert client.delete(f"/api/fare-watches/{w['id']}", headers=h).status_code == 200
    assert client.get(f"/api/fare-watches/{w['id']}", headers=h).status_code == 404


# ── Check now ─────────────────────────────────────────────────────────────────


def test_check_now_reports_a_drop(client, alice, monkeypatch):
    _, h = alice
    w = _create(client, h).json()
    get_cache().clear()
    serp_flights._call.return_value = _serp([430.0])
    monkeypatch.setattr(fare_watch, "utcnow", lambda: NOW + timedelta(hours=1))
    r = client.post(f"/api/fare-watches/{w['id']}/check", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["check_status"] == "checked"
    assert body["notification"]["kind"] == "fare_drop"
    assert "user_id" not in body["notification"]
    assert body["last_price"] == 430.0
    assert [p["price"] for p in body["history"]] == [480.0, 430.0]


def test_check_now_with_spent_budget_is_429(client, alice, monkeypatch):
    _, h = alice
    w = _create(client, h).json()
    get_cache().clear()
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 1)
    r = client.post(f"/api/fare-watches/{w['id']}/check", headers=h)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) == 12 * 3600
    assert "tomorrow" in r.json()["detail"]


def test_check_now_on_expired_watch_is_409(client, alice):
    _, h = alice
    w = _create(client, h).json()
    fare_watch_db.update_watch(w["id"], status="expired")
    assert (
        client.post(f"/api/fare-watches/{w['id']}/check", headers=h).status_code == 409
    )


def test_check_now_is_rate_limited(client, alice, monkeypatch):
    _, h = alice
    w = _create(client, h).json()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_light_ai", 1)
    rate_limit.limiter._hits.clear()
    try:
        assert (
            client.post(f"/api/fare-watches/{w['id']}/check", headers=h).status_code
            == 200
        )
        r = client.post(f"/api/fare-watches/{w['id']}/check", headers=h)
        assert r.status_code == 429
        assert "Retry-After" in r.headers
    finally:
        rate_limit.limiter._hits.clear()


def test_check_now_without_serpapi_is_503(client, alice, monkeypatch):
    _, h = alice
    w = _create(client, h).json()
    monkeypatch.setattr(settings, "serpapi_key", "")
    assert (
        client.post(f"/api/fare-watches/{w['id']}/check", headers=h).status_code == 503
    )


# ── Notifications API ─────────────────────────────────────────────────────────


def _note(user, title="t", kind="fare_drop"):
    return notifications_db.add_notification(
        user["id"], kind, title, "b", {"watch_id": 1}, now=NOW
    )


def test_notifications_list_count_and_read(client, alice, bob):
    u, h = alice
    a, b = _note(u, "a"), _note(u, "b")
    _note(bob[0], "bob's")
    assert client.get("/api/notifications/unread-count", headers=h).json() == {
        "count": 2
    }
    page = client.get("/api/notifications", headers=h).json()
    assert {n["title"] for n in page["items"]} == {"a", "b"}
    assert all("user_id" not in n for n in page["items"])
    assert page["unread"] == 2 and page["total"] == 2
    r = client.post("/api/notifications/read", json={"ids": [a["id"]]}, headers=h)
    assert r.json() == {"updated": 1, "unread": 1}
    unread = client.get("/api/notifications?unread_only=true", headers=h).json()
    assert [n["id"] for n in unread["items"]] == [b["id"]]
    r = client.post("/api/notifications/read", json={"all": True}, headers=h)
    assert r.json()["unread"] == 0
    assert client.get("/api/notifications/unread-count", headers=bob[1]).json() == {
        "count": 1
    }


def test_notifications_pagination_bounds(client, alice):
    u, h = alice
    for i in range(3):
        _note(u, f"n{i}")
    page = client.get("/api/notifications?limit=2&offset=0", headers=h).json()
    assert len(page["items"]) == 2 and page["total"] == 3
    assert client.get("/api/notifications?limit=0", headers=h).status_code == 422
    assert client.get("/api/notifications?limit=101", headers=h).status_code == 422


def test_read_needs_ids_or_all(client, alice):
    r = client.post("/api/notifications/read", json={}, headers=alice[1])
    assert r.status_code == 422


def test_notifications_require_auth(client):
    assert client.get("/api/notifications").status_code == 401
    assert client.get("/api/notifications/unread-count").status_code == 401


# ── Unsubscribe link ──────────────────────────────────────────────────────────


def test_unsubscribe_turns_off_email_without_login(client, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    _, h = _user(email=f"{uuid.uuid4().hex[:6]}@example.com")
    w = _create(client, h, email_enabled=True).json()
    token = alert_email.unsubscribe_token(w["id"])
    r = client.get(f"/api/fare-watches/unsubscribe?token={token}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "won't email you" in r.text
    got = fare_watch_db.get_watch(w["id"])
    assert got["email_enabled"] is False
    assert got["status"] == "active"  # in-app alerts keep going


@pytest.mark.parametrize("token", ["", "garbage", "a.b.c"])
def test_unsubscribe_rejects_bad_tokens(client, token):
    r = client.get(f"/api/fare-watches/unsubscribe?token={token}")
    assert r.status_code == 400


def test_unsubscribe_rejects_a_login_token(client, alice):
    token = alice[1]["Authorization"].split()[1]
    assert client.get(f"/api/fare-watches/unsubscribe?token={token}").status_code == 400


def test_unsubscribe_for_a_deleted_watch_is_friendly(client):
    token = alert_email.unsubscribe_token(999_999)
    r = client.get(f"/api/fare-watches/unsubscribe?token={token}")
    assert r.status_code == 200


# ── Account email + capability flags ──────────────────────────────────────────


def test_me_includes_email_and_it_can_be_set(client, alice):
    _, h = alice
    assert client.get("/api/auth/me", headers=h).json()["email"] is None
    addr = f"{uuid.uuid4().hex[:6]}@Example.com"
    r = client.put("/api/auth/email", json={"email": f"  {addr} "}, headers=h)
    assert r.status_code == 200
    assert r.json()["email"] == addr.lower()
    assert client.get("/api/auth/me", headers=h).json()["email"] == addr.lower()
    r = client.put("/api/auth/email", json={"email": ""}, headers=h)
    assert r.json()["email"] is None


def test_login_response_includes_email(client, monkeypatch):
    monkeypatch.setattr("app.db.users_db._hash", real_hash)  # a real login
    addr = f"{uuid.uuid4().hex[:6]}@example.com"
    u = create_user(f"fw-{uuid.uuid4().hex[:8]}", "pw-123456789", email=addr)
    r = client.post(
        "/api/auth/login", json={"username": u["username"], "password": "pw-123456789"}
    )
    assert r.json()["user"]["email"] == addr


@pytest.mark.parametrize("bad", ["nope", "a@b", "a b@c.de", "@x.com", "x@.com"])
def test_email_is_validated(client, alice, bad):
    r = client.put("/api/auth/email", json={"email": bad}, headers=alice[1])
    assert r.status_code == 422


def test_email_already_used_is_409(client, alice, bob):
    addr = f"{uuid.uuid4().hex[:6]}@example.com"
    client.put("/api/auth/email", json={"email": addr}, headers=alice[1])
    r = client.put("/api/auth/email", json={"email": addr}, headers=bob[1])
    assert r.status_code == 409


def test_clearing_email_turns_off_email_alerts(client, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    _, h = _user(email=f"{uuid.uuid4().hex[:6]}@example.com")
    w = _create(client, h, email_enabled=True).json()
    client.put("/api/auth/email", json={"email": ""}, headers=h)
    assert fare_watch_db.get_watch(w["id"])["email_enabled"] is False


def test_health_reports_alert_capabilities(client, monkeypatch):
    monkeypatch.setattr(settings, "fare_watch_enabled", True)
    body = client.get("/health").json()
    assert body["fare_watch_available"] is True
    assert body["email_alerts_available"] is False
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "fare_watch_enabled", False)
    body = client.get("/health").json()
    assert body["email_alerts_available"] is True
    assert body["fare_watch_available"] is False


# ── Manual checks hold the lease (no double check with the scheduler) ────────


def test_scheduler_cannot_claim_a_watch_during_its_baseline_check(
    client, alice, monkeypatch
):
    claimed_during_fetch = []
    real_fetch = fare_watch.fetch_fares

    async def fetch(watch, key):
        claimed_during_fetch.extend(
            fare_watch_db.claim_due(NOW, NOW + timedelta(minutes=10), 50)
        )
        return await real_fetch(watch, key)

    monkeypatch.setattr(fare_watch, "fetch_fares", fetch)
    w = _create(client, alice[1]).json()
    assert w["id"] not in claimed_during_fetch
    assert [p["price"] for p in w["history"]] == [480.0]
    assert fare_watch_db.get_watch(w["id"])["lease_until"] is None


def test_check_now_while_the_scheduler_holds_the_watch_is_409(client, alice):
    _, h = alice
    w = _create(client, h).json()
    fare_watch_db.update_watch(
        w["id"], lease_until=(NOW + timedelta(minutes=5)).isoformat()
    )
    r = client.post(f"/api/fare-watches/{w['id']}/check", headers=h)
    assert r.status_code == 409
    assert "checking" in r.json()["detail"]
    serp_flights._call.reset_mock()
    assert serp_flights._call.call_count == 0


def test_claim_watch_is_exclusive(alice):
    u, _ = alice
    w = fare_watch_db.create_watch(
        u["id"],
        {
            "origin_code": "BER",
            "destination_code": "LIS",
            "origin_label": "Berlin",
            "destination_label": "Lisbon",
            "departure_date": "2026-12-01",
            "num_travelers": 1,
        },
        now=NOW,
        lease_until=NOW + timedelta(minutes=10),
    )
    assert fare_watch_db.claim_watch(w["id"], NOW, NOW + timedelta(minutes=10)) is False
    later = NOW + timedelta(minutes=11)
    assert (
        fare_watch_db.claim_watch(w["id"], later, later + timedelta(minutes=10)) is True
    )
    assert (
        fare_watch_db.claim_watch(w["id"], later, later + timedelta(minutes=10))
        is False
    )
