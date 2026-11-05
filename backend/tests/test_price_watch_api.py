"""Price watch API with the fake ``test`` source: kind dispatch, create /
no-live-price / already watching, ownership 404s, limits, check now,
match, unsubscribe and rate limits."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core import rate_limit
from app.core.auth import create_access_token
from app.core.config import settings
from app.db import fare_watch_db, notifications_db, price_watch_db
from app.db.database import get_connection
from app.db.users_db import create_user
from app.services import alert_email, fare_watch, price_watch

from .price_watch_fakes import FakeSource, QuotaError, gone, ok

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _env(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    monkeypatch.setattr(settings, "serpapi_key", "test-key")
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 200)
    monkeypatch.setattr(settings, "fare_watch_max_active_per_user", 10)
    monkeypatch.setattr(fare_watch, "utcnow", lambda: NOW)
    with get_connection() as conn:
        conn.execute("DELETE FROM fare_watch_quota")
        conn.execute("DELETE FROM fare_watch_user_quota")


@pytest.fixture
def src():
    s = FakeSource()
    price_watch.register_source(s)
    yield s
    price_watch.unregister_source("test")


def _user(email=None):
    u = create_user(f"pa-{uuid.uuid4().hex[:8]}", "pw-123456789", email=email)
    token = create_access_token({"sub": u["username"]})
    return u, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alice():
    return _user()


@pytest.fixture
def bob():
    return _user()


def _create(client, h, name="Lumen Hotel", **over):
    body = {"kind": "test", "test": {"name": name, "price": 400.0}}
    body.update(over)
    return client.post("/api/price-watches", json=body, headers=h)


# ── Create ────────────────────────────────────────────────────────────────────


def test_create_matches_and_takes_the_baseline(client, alice, src):
    u, h = alice
    r = _create(client, h)
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["already_watching"] is False
    assert (w["kind"], w["title"], w["subtitle"]) == (
        "test",
        "Lumen Hotel",
        "Testville · 1–5 Feb",
    )
    assert w["subject"] == {"name": "Lumen Hotel", "token": "tok-1"}
    assert (w["baseline_price"], w["last_price"], w["lowest_price"]) == (400.0,) * 3
    assert w["status"] == "active" and w["check_count"] == 1
    assert w["expires_on"] == "2027-02-01"
    assert w["link"] == "https://example.test/thing"
    assert w["last_observation"]["unit_price"] == 100.0
    assert [p["price"] for p in w["history"]] == [400.0]
    for hidden in ("user_id", "lease_until", "last_error", "match_key"):
        assert hidden not in w
    assert src.created[0]["key"] == "test-key"
    assert src.created[0]["user"] == u["id"]
    assert fare_watch_db.calls_used(NOW.date().isoformat()) == 1


def test_create_charges_the_calls_the_match_spent(client, alice, src):
    _, h = alice
    src.create_calls = 3
    assert _create(client, h).status_code == 200
    day = NOW.date().isoformat()
    assert fare_watch_db.calls_used(day) == 3
    src.create_calls = 0  # all cached: the reserved call is given back
    assert _create(client, h, name="Other").status_code == 200
    assert fare_watch_db.calls_used(day) == 3


def test_create_never_settles_the_pool_past_the_budget(client, alice, src):
    # One call held at 199 of 200; the match spent 3 — the pool stops at 200
    day = NOW.date().isoformat()
    fare_watch_db.reserve_calls(day, 199, 200)
    _, h = alice
    src.create_calls = 3
    assert _create(client, h).status_code == 200
    assert fare_watch_db.calls_used(day) == 200


def test_adjust_calls_clamps_additions_at_the_budget_and_share():
    day = "2031-01-01"
    fare_watch_db.adjust_calls(day, 5, user_id="cap-u", budget=4, user_cap=3)
    assert fare_watch_db.calls_used(day) == 4
    assert fare_watch_db.user_calls_used(day, "cap-u") == 3
    fare_watch_db.adjust_calls(day, 2, user_id="cap-u", budget=4, user_cap=3)
    assert fare_watch_db.calls_used(day) == 4  # already at the budget
    fare_watch_db.adjust_calls(day, -3, user_id="cap-u", budget=4, user_cap=3)
    assert fare_watch_db.calls_used(day) == 1  # giving back is never clamped
    assert fare_watch_db.user_calls_used(day, "cap-u") == 0


def test_create_with_target_and_plan(client, alice, src):
    _, h = alice
    r = _create(
        client, h, alert_mode="below_target", target_price=350, plan_id=None
    ).json()
    assert (r["alert_mode"], r["target_price"]) == ("below_target", 350.0)
    assert r["already_below_target"] is False


def test_target_mode_needs_a_target(client, alice, src):
    _, h = alice
    assert _create(client, h, alert_mode="below_target").status_code == 422


def test_unknown_kind_is_422(client, alice, src):
    _, h = alice
    r = client.post(
        "/api/price-watches", json={"kind": "boat", "boat": {"name": "x"}}, headers=h
    )
    assert r.status_code == 422
    assert "can't watch" in r.json()["detail"]


def test_invalid_spec_is_422_with_the_source_message(client, alice, src):
    _, h = alice
    r = _create(client, h, test={"name": " "})
    assert r.status_code == 422
    assert r.json()["detail"] == "Tell us which thing to watch."
    assert src.created == []


def test_oversized_spec_is_422(client, alice, src):
    _, h = alice
    r = _create(client, h, test={"name": "x", "junk": "y" * 9000})
    assert r.status_code == 422


def test_no_live_price_is_422_with_suggestions(client, alice, src):
    _, h = alice
    r = _create(client, h, test={"name": "Mystery", "no_match": True})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "no_live_price"
    assert body["message"] == body["detail"]
    assert body["suggestions"] == [{"name": "Other thing", "price": 90.0}]
    assert body["estimate"]["source"] == "ai_estimate"
    assert price_watch_db.list_watches(alice[0]["id"]) == []
    assert fare_watch_db.calls_used(NOW.date().isoformat()) == 1


def test_baseline_unavailable_is_no_live_price(client, alice, src, monkeypatch):
    _, h = alice
    real = src.create

    async def create(spec, user, key):
        c = await real(spec, user, key)
        c.baseline = gone()
        return c

    monkeypatch.setattr(src, "create", create)
    r = _create(client, h)
    assert r.status_code == 422 and r.json()["code"] == "no_live_price"


def test_subject_ending_today_cannot_be_watched(client, alice, src):
    _, h = alice
    r = _create(client, h, test={"name": "x", "expires_on": "2026-11-04"})
    assert r.status_code == 422


def test_create_again_returns_the_existing_watch_without_live_calls(client, alice, src):
    _, h = alice
    first = _create(client, h).json()
    again = _create(client, h, name="lumen hotel")
    assert again.status_code == 200
    assert again.json()["id"] == first["id"]
    assert again.json()["already_watching"] is True
    assert len(src.created) == 1


def test_an_expired_watch_does_not_block_a_new_one(client, alice, src):
    _, h = alice
    first = _create(client, h).json()
    price_watch_db.update_watch(first["id"], status="expired")
    assert _create(client, h).json()["id"] != first["id"]


def test_503_without_serpapi(client, alice, src, monkeypatch):
    _, h = alice
    monkeypatch.setattr(settings, "serpapi_key", "")
    assert _create(client, h).status_code == 503


def test_live_source_failure_is_502(client, alice, src, monkeypatch):
    _, h = alice

    async def boom(spec, user, key):
        raise RuntimeError("HTTP 500 from serpapi with api_key=secret")

    monkeypatch.setattr(src, "create", boom)
    r = _create(client, h)
    assert r.status_code == 502
    assert "secret" not in r.text


def test_live_quota_on_create_is_429(client, alice, src, monkeypatch):
    _, h = alice

    async def quota(spec, user, key):
        raise QuotaError("quota")

    monkeypatch.setattr(src, "create", quota)
    r = _create(client, h)
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_spent_budget_refuses_create(client, alice, src, monkeypatch):
    _, h = alice
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 2)
    fare_watch_db.reserve_calls(NOW.date().isoformat(), 2, 2)
    r = _create(client, h)
    assert r.status_code == 429
    assert r.headers["Retry-After"] == str(12 * 3600)
    assert src.created == []


def test_active_limit_counts_fare_and_price_watches(client, alice, src, monkeypatch):
    u, h = alice
    monkeypatch.setattr(settings, "fare_watch_max_active_per_user", 2)
    fare_watch_db.create_watch(
        u["id"],
        {
            "origin_code": "BER",
            "destination_code": "LIS",
            "origin_label": "Berlin",
            "destination_label": "Lisbon",
            "departure_date": "2027-02-01",
        },
        now=NOW,
    )
    assert _create(client, h, name="A").status_code == 200
    r = _create(client, h, name="B")
    assert r.status_code == 409
    assert "2 active watches" in r.json()["detail"]
    # …and the fare-watch route counts the price watch too
    r = client.post(
        "/api/fare-watches",
        json={"origin": "BER", "destination": "MAD", "departure_date": "2026-12-01"},
        headers=h,
    )
    assert r.status_code == 409


def test_email_needs_an_address_and_smtp(client, src, monkeypatch):
    _, h = _user()
    r = _create(client, h, email_enabled=True)
    assert r.status_code == 422
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    r = _create(client, h, email_enabled=True)
    assert r.status_code == 422 and "email address" in r.json()["detail"]
    _, h2 = _user(email=f"{uuid.uuid4().hex[:6]}@example.com")
    assert _create(client, h2, email_enabled=True).json()["email_enabled"] is True


def test_auth_required(client, src):
    assert client.get("/api/price-watches").status_code == 401
    assert client.post("/api/price-watches", json={"kind": "test"}).status_code == 401


# ── Read / ownership ──────────────────────────────────────────────────────────


def test_list_is_per_user_and_filters_by_kind(client, alice, bob, src):
    _, ha = alice
    _, hb = bob
    w = _create(client, ha).json()
    assert [x["id"] for x in client.get("/api/price-watches", headers=ha).json()] == [
        w["id"]
    ]
    assert client.get("/api/price-watches", headers=hb).json() == []
    assert client.get("/api/price-watches?kind=hotel", headers=ha).json() == []


@pytest.mark.parametrize(
    "method,suffix",
    [("get", ""), ("patch", ""), ("delete", ""), ("post", "/check")],
)
def test_someone_elses_watch_is_404(client, alice, bob, src, method, suffix):
    _, ha = alice
    _, hb = bob
    w = _create(client, ha).json()
    kw = {"json": {"status": "paused"}} if method == "patch" else {}
    r = getattr(client, method)(
        f"/api/price-watches/{w['id']}{suffix}", headers=hb, **kw
    )
    assert r.status_code == 404
    assert price_watch_db.get_watch(w["id"]) is not None


def test_get_and_delete(client, alice, src):
    _, h = alice
    w = _create(client, h).json()
    assert (
        client.get(f"/api/price-watches/{w['id']}", headers=h).json()["id"] == w["id"]
    )
    assert client.delete(f"/api/price-watches/{w['id']}", headers=h).json() == {
        "deleted": True
    }
    assert client.get(f"/api/price-watches/{w['id']}", headers=h).status_code == 404


# ── Update ────────────────────────────────────────────────────────────────────


def test_pause_resume_and_edit(client, alice, src):
    _, h = alice
    w = _create(client, h).json()
    url = f"/api/price-watches/{w['id']}"
    assert (
        client.patch(url, json={"status": "paused"}, headers=h).json()["status"]
        == "paused"
    )
    assert (
        client.patch(url, json={"status": "active"}, headers=h).json()["status"]
        == "active"
    )
    r = client.patch(
        url, json={"alert_mode": "below_target", "target_price": 300}, headers=h
    ).json()
    assert (r["alert_mode"], r["target_price"]) == ("below_target", 300.0)
    assert (
        client.patch(
            url, json={"alert_mode": "below_target", "target_price": None}, headers=h
        ).status_code
        == 200
    )


def test_target_mode_without_target_is_422(client, alice, src):
    _, h = alice
    w = _create(client, h).json()
    r = client.patch(
        f"/api/price-watches/{w['id']}", json={"alert_mode": "below_target"}, headers=h
    )
    assert r.status_code == 422


def test_retry_after_error_clears_strikes_and_checks_now(client, alice, src):
    _, h = alice
    w = _create(client, h).json()
    price_watch_db.update_watch(
        w["id"], status="error", failure_count=3, unavailable_count=3, last_error="x"
    )
    r = client.patch(
        f"/api/price-watches/{w['id']}", json={"status": "active"}, headers=h
    ).json()
    assert (r["status"], r["failure_count"], r["unavailable_count"]) == (
        "active",
        0,
        0,
    )
    assert r["next_check_at"] == NOW.isoformat()
    assert r["problem"] is None


def test_resume_respects_the_limit_and_expired_cannot_resume(
    client, alice, src, monkeypatch
):
    _, h = alice
    a = _create(client, h, name="A").json()
    client.patch(f"/api/price-watches/{a['id']}", json={"status": "paused"}, headers=h)
    _create(client, h, name="B")
    monkeypatch.setattr(settings, "fare_watch_max_active_per_user", 1)
    r = client.patch(
        f"/api/price-watches/{a['id']}", json={"status": "active"}, headers=h
    )
    assert r.status_code == 409
    price_watch_db.update_watch(a["id"], status="expired")
    r = client.patch(
        f"/api/price-watches/{a['id']}", json={"status": "active"}, headers=h
    )
    assert r.status_code == 409


# ── Check now ─────────────────────────────────────────────────────────────────


def test_check_now_reports_an_alert(client, alice, src):
    _, h = alice
    w = _create(client, h).json()
    src.queue.append(ok(370.0))
    r = client.post(f"/api/price-watches/{w['id']}/check", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["check_status"] == "checked"
    assert body["last_price"] == 370.0
    assert body["notification"]["kind"] == "test_drop"
    assert body["notification"]["data"]["watch_kind"] == "test"
    assert "user_id" not in body["notification"]


def test_check_now_unavailable(client, alice, src):
    _, h = alice
    w = _create(client, h).json()
    src.queue.append(gone())
    body = client.post(f"/api/price-watches/{w['id']}/check", headers=h).json()
    assert body["check_status"] == "unavailable"
    assert body["notification"] is None
    assert body["last_observation"]["status"] == "unavailable"


def test_check_now_while_leased_is_409(client, alice, src):
    _, h = alice
    w = _create(client, h).json()
    price_watch_db.claim_watch(w["id"], NOW, NOW + timedelta(minutes=10))
    assert (
        client.post(f"/api/price-watches/{w['id']}/check", headers=h).status_code == 409
    )


def test_check_now_on_expired_is_409_and_without_serpapi_503(
    client, alice, src, monkeypatch
):
    _, h = alice
    w = _create(client, h).json()
    price_watch_db.update_watch(w["id"], status="expired")
    assert (
        client.post(f"/api/price-watches/{w['id']}/check", headers=h).status_code == 409
    )
    monkeypatch.setattr(settings, "serpapi_key", "")
    assert (
        client.post(f"/api/price-watches/{w['id']}/check", headers=h).status_code == 503
    )


def test_check_now_out_of_budget_is_429(client, alice, src, monkeypatch):
    _, h = alice
    w = _create(client, h).json()
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 1)
    r = client.post(f"/api/price-watches/{w['id']}/check", headers=h)
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    assert price_watch_db.get_watch(w["id"])["lease_until"] is None


# ── Match ─────────────────────────────────────────────────────────────────────


def test_match_finds_the_watch_without_live_calls(client, alice, bob, src):
    _, ha = alice
    _, hb = bob
    w = _create(client, ha).json()
    q = {"kind": "test", "test": {"name": "LUMEN hotel"}}
    r = client.post("/api/price-watches/match", json=q, headers=ha).json()
    assert r["watch"]["id"] == w["id"]
    assert client.post("/api/price-watches/match", json=q, headers=hb).json() == {
        "watch": None
    }
    assert len(src.created) == 1


@pytest.mark.parametrize(
    "q",
    [
        {"kind": "test", "test": {"name": ""}},
        {"kind": "nope", "nope": {"name": "x"}},
        {"kind": "test"},
    ],
)
def test_match_with_nothing_to_match_is_none(client, alice, src, q):
    _, h = alice
    r = client.post("/api/price-watches/match", json=q, headers=h)
    assert r.status_code == 200 and r.json() == {"watch": None}


# ── Unsubscribe ───────────────────────────────────────────────────────────────


def test_unsubscribe_confirm_then_post(client, src):
    _, h = _user(email=f"{uuid.uuid4().hex[:6]}@example.com")
    settings_smtp = settings.smtp_host
    try:
        settings.smtp_host = "smtp.test"
        w = _create(client, h, email_enabled=True).json()
    finally:
        settings.smtp_host = settings_smtp
    token = alert_email.unsubscribe_token(w["id"], alert_email.PRICE_UNSUB_PURPOSE)
    page = client.get(f"/api/price-watches/unsubscribe?token={token}")
    assert page.status_code == 200 and "Lumen Hotel" in page.text
    assert price_watch_db.get_watch(w["id"])["email_enabled"] is True
    done = client.post(f"/api/price-watches/unsubscribe?token={token}")
    assert done.status_code == 200
    assert price_watch_db.get_watch(w["id"])["email_enabled"] is False


def test_a_fare_token_cannot_unsubscribe_a_price_watch(client, alice, src):
    _, h = alice
    w = _create(client, h).json()
    token = alert_email.unsubscribe_token(w["id"])  # fare purpose
    assert (
        client.post(f"/api/price-watches/unsubscribe?token={token}").status_code == 400
    )


def test_unsubscribe_for_a_deleted_watch(client):
    token = alert_email.unsubscribe_token(999_999, alert_email.PRICE_UNSUB_PURPOSE)
    r = client.post(f"/api/price-watches/unsubscribe?token={token}")
    assert r.status_code == 200 and "no longer exists" in r.text


def test_removing_the_email_address_turns_price_emails_off(client, src, monkeypatch):
    u, h = _user(email=f"{uuid.uuid4().hex[:6]}@example.com")
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    w = _create(client, h, email_enabled=True).json()
    r = client.put("/api/auth/email", json={"email": ""}, headers=h)
    assert r.status_code == 200, r.text
    assert price_watch_db.get_watch(w["id"])["email_enabled"] is False


# ── Notifications and rate limits ─────────────────────────────────────────────


def test_price_notifications_show_in_the_bell(client, alice, src):
    u, h = alice
    w = _create(client, h).json()
    src.queue.append(ok(370.0))
    client.post(f"/api/price-watches/{w['id']}/check", headers=h)
    items = client.get("/api/notifications", headers=h).json()["items"]
    assert items[0]["kind"] == "test_drop"
    assert items[0]["data"]["links"]["alerts"] == f"/alerts?kind=test&watch={w['id']}"
    assert notifications_db.count_unread(u["id"]) == 1


def test_create_and_check_use_the_light_ai_bucket(client, alice, src, monkeypatch):
    _, h = alice
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_light_ai", 1)
    rate_limit.limiter._hits.clear()
    try:
        assert _create(client, h, name="A").status_code == 200
        r = _create(client, h, name="B")
        assert r.status_code == 429 and "Retry-After" in r.headers
        # reads aren't limited
        assert client.get("/api/price-watches", headers=h).status_code == 200
    finally:
        rate_limit.limiter._hits.clear()


# ── Fix round 1 ───────────────────────────────────────────────────────────────


class SpentError(RuntimeError):
    calls = 3


def test_create_failure_settles_the_calls_the_source_reports(
    client, alice, src, monkeypatch
):
    _, h = alice

    async def boom(spec, user, key):
        raise SpentError("HTTP 500")

    monkeypatch.setattr(src, "create", boom)
    assert _create(client, h).status_code == 502
    assert fare_watch_db.calls_used(NOW.date().isoformat()) == 3


def test_invalid_spec_after_spending_keeps_the_spent_calls(
    client, alice, src, monkeypatch
):
    from app.services.price_watch import InvalidSpec

    _, h = alice

    class SpentInvalid(InvalidSpec):
        calls = 2

    async def bad(spec, user, key):
        raise SpentInvalid("That listing isn't a tour.")

    monkeypatch.setattr(src, "create", bad)
    r = _create(client, h)
    assert r.status_code == 422 and r.json()["detail"] == "That listing isn't a tour."
    assert fare_watch_db.calls_used(NOW.date().isoformat()) == 2


def test_match_ignores_an_oversized_spec(client, alice, src):
    _, h = alice
    q = {"kind": "test", "test": {"name": "x", "junk": "y" * 9000}}
    r = client.post("/api/price-watches/match", json=q, headers=h)
    assert r.status_code == 200 and r.json() == {"watch": None}


def test_check_now_with_a_broken_compose_answers_and_frees_the_watch(
    client, alice, src, monkeypatch
):
    _, h = alice
    w = _create(client, h).json()

    def broken(kind, watch, obs, ref):
        raise RuntimeError("compose broke")

    monkeypatch.setattr(src, "compose", broken)
    src.queue.append(ok(300.0))
    r = client.post(f"/api/price-watches/{w['id']}/check", headers=h)
    assert r.status_code == 200 and r.json()["check_status"] == "failed"
    assert price_watch_db.get_watch(w["id"])["lease_until"] is None


def test_fare_limit_message_counts_watches_not_fares(client, alice, src, monkeypatch):
    u, h = alice
    monkeypatch.setattr(settings, "fare_watch_max_active_per_user", 1)
    assert _create(client, h).status_code == 200
    r = client.post(
        "/api/fare-watches",
        json={"origin": "BER", "destination": "MAD", "departure_date": "2026-12-01"},
        headers=h,
    )
    assert r.status_code == 409
    assert (
        "1 active watches" in r.json()["detail"]
        or "1 active watch" in r.json()["detail"]
    )
    assert "fares" not in r.json()["detail"]
