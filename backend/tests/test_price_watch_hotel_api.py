"""Hotel price watches end to end through ``/api/price-watches`` with the real
``hotel`` source registered: create, 422 with suggestions, create from a
suggestion, already watching, check now (drop + email), sold-out looks and
the scheduler pass. SerpAPI answers are the recorded fixtures
(``hotel_prices._call`` stubbed); no network."""

import copy
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.auth import create_access_token
from app.core.cache import get_cache
from app.core.config import settings
from app.db import fare_watch_db, notifications_db, price_watch_db
from app.db.database import get_connection
from app.db.users_db import create_user
from app.services import alert_email, fare_watch, hotel_prices, price_watch
from app.services.price_sources.hotel import SOURCE

from .test_alert_email import FakeSMTP

FIXTURES = Path(__file__).parent / "fixtures" / "serpapi" / "hotels"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
LUMEN_TOKEN = "ChoIkamS5OLO9d2QARoNL2cvMTFrODM4N24zORAB"
BROWNS_TOKEN = "ChkIhLCQwvjO2IYWGg0vZy8xMXE0bTZieDkyEAE"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def lumen_at(total: float, nightly: float) -> dict:
    """The recorded Lumen property look with another price."""
    data = copy.deepcopy(load("property_details_lumen_generic_q.json"))
    data["total_rate"]["extracted_lowest"] = total
    data["rate_per_night"]["extracted_lowest"] = nightly
    return data


@pytest.fixture(autouse=True)
def _env(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    monkeypatch.setattr(settings, "serpapi_key", "test-key")
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 200)
    monkeypatch.setattr(settings, "fare_watch_max_active_per_user", 10)
    monkeypatch.setattr(fare_watch, "utcnow", lambda: NOW)
    price_watch.register_source(SOURCE)
    get_cache().clear()
    with get_connection() as conn:
        conn.execute("DELETE FROM fare_watch_quota")
        conn.execute("DELETE FROM fare_watch_user_quota")
    yield
    get_cache().clear()


def serp(*responses):
    return patch.object(
        hotel_prices,
        "_call",
        AsyncMock(side_effect=[copy.deepcopy(r) for r in responses]),
    )


def _user(email=None):
    u = create_user(f"ph-{uuid.uuid4().hex[:8]}", "pw-123456789", email=email)
    token = create_access_token({"sub": u["username"]})
    return u, {"Authorization": f"Bearer {token}"}


def _hotel(**over):
    h = {
        "name": "Lumen Hotel",
        "city": "Lisbon",
        "check_in": "2026-12-10",
        "check_out": "2026-12-14",
        "adults": 2,
    }
    h.update(over)
    return h


def _create(client, h, hotel=None, **over):
    body = {"kind": "hotel", "hotel": hotel or _hotel()}
    body.update(over)
    return client.post("/api/price-watches", json=body, headers=h)


def _create_lumen(client, h, **over):
    with serp(
        load("named_search_lumen_single_property.json"),
        load("property_details_lumen_generic_q.json"),
    ):
        r = _create(client, h, **over)
    assert r.status_code == 200, r.text
    get_cache().clear()  # later looks go to "SerpAPI" again
    return r.json()


# ── Create ────────────────────────────────────────────────────────────────────


def test_create_matches_the_hotel_and_stores_the_property(client):
    u, h = _user()
    w = _create_lumen(client, h)
    assert w["kind"] == "hotel" and w["already_watching"] is False
    assert w["title"] == "Lumen Hotel & The Lisbon Light Show"
    assert w["subtitle"] == "10–14 Dec · 2 guests · 1 room"
    assert w["subject"]["property_token"] == LUMEN_TOKEN
    assert w["subject"]["requested_name"] == "Lumen Hotel"
    assert w["expires_on"] == "2026-12-10"
    assert (w["baseline_price"], w["last_price"]) == (368.0, 368.0)
    assert w["last_observation"]["unit_price"] == 92.0
    assert w["last_observation"]["source"] == "google_hotels"
    assert w["link"] == "https://www.lumenhotel.pt/"
    assert [p["price"] for p in w["history"]] == [368.0]
    # Two live looks: the search and the property's own price
    assert fare_watch_db.calls_used(NOW.date().isoformat()) == 2


def test_no_confident_match_is_422_with_suggestions_and_the_estimate(client):
    u, h = _user()
    with serp(load("city_search_lisbon.json")):
        r = _create(client, h, _hotel(name="Lisbon Light Hotel", estimate_total=410))
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "no_live_price"
    assert body["message"] == (
        "We couldn't find live prices for this hotel on Google Hotels."
    )
    assert body["estimate"]["price"] == 410.0
    assert body["estimate"]["source"] == "ai_estimate"
    assert 1 <= len(body["suggestions"]) <= 3
    first = body["suggestions"][0]
    assert first["title"] == "Lumen Hotel & The Lisbon Light Show"
    assert first["price"] == 398.0 and first["nightly"] == 100.0
    assert first["spec"]["property_token"] == LUMEN_TOKEN
    assert price_watch_db.list_watches(u["id"], "hotel") == []
    assert fare_watch_db.calls_used(NOW.date().isoformat()) == 1


def test_watching_a_suggestion_prices_its_token_directly(client):
    _, h = _user()
    with serp(load("city_search_lisbon.json")):
        r = _create(client, h, _hotel(name="Lisbon Light Hotel"))
    pick = r.json()["suggestions"][0]["spec"]
    with serp(load("property_details_lumen_generic_q.json")) as call:
        r = _create(client, h, pick)
    assert r.status_code == 200, r.text
    assert call.await_count == 1
    assert call.await_args.args[0]["property_token"] == LUMEN_TOKEN
    w = r.json()
    assert w["title"] == "Lumen Hotel & The Lisbon Light Show"
    assert w["baseline_price"] == 368.0


def test_already_watching_spends_no_calls(client):
    _, h = _user()
    first = _create_lumen(client, h)
    used = fare_watch_db.calls_used(NOW.date().isoformat())
    with serp() as call:
        r = _create(client, h, _hotel(name="  lumen HOTEL "))
    assert r.status_code == 200
    assert r.json()["already_watching"] is True and r.json()["id"] == first["id"]
    assert call.await_count == 0
    assert fare_watch_db.calls_used(NOW.date().isoformat()) == used


def test_match_finds_the_watch_from_the_cards_spec(client):
    _, h = _user()
    w = _create_lumen(client, h)
    with serp() as call:
        r = client.post(
            "/api/price-watches/match",
            json={"kind": "hotel", "hotel": _hotel(estimate_total=999)},
            headers=h,
        )
        other = client.post(
            "/api/price-watches/match",
            json={"kind": "hotel", "hotel": _hotel(adults=3)},
            headers=h,
        )
    assert r.json()["watch"]["id"] == w["id"]
    assert other.json()["watch"] is None
    assert call.await_count == 0


@pytest.mark.parametrize(
    "bad,detail",
    [
        ({"adults": 0}, "adults"),
        ({"check_out": "2026-12-09"}, "Check-out must be after check-in"),
        ({"check_in": "2026-10-01", "check_out": "2026-10-03"}, "too soon"),
        ({"name": ""}, "name"),
    ],
)
def test_invalid_hotel_specs_are_422_without_live_calls(client, bad, detail):
    _, h = _user()
    with serp() as call:
        r = _create(client, h, _hotel(**bad))
    assert r.status_code == 422
    assert detail in r.json()["detail"]
    assert call.await_count == 0
    assert fare_watch_db.calls_used(NOW.date().isoformat()) == 0


def test_serpapi_failure_while_creating_is_502(client):
    _, h = _user()
    with patch.object(
        hotel_prices, "_call", AsyncMock(side_effect=hotel_prices.SerpAPIError("x"))
    ):
        r = _create(client, h)
    assert r.status_code == 502


# ── Check now ─────────────────────────────────────────────────────────────────


def test_check_now_drop_alerts_with_hotel_copy_and_email(client, monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(alert_email.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_from", "Alerts <alerts@trip.test>")
    monkeypatch.setattr(settings, "app_base_url", "https://trip.test/")
    u, h = _user(email=f"{uuid.uuid4().hex[:6]}@example.com")
    w = _create_lumen(client, h, email_enabled=True)
    with serp(lumen_at(322, 80.5)) as call:
        r = client.post(f"/api/price-watches/{w['id']}/check", headers=h)
    assert r.status_code == 200, r.text
    assert call.await_args.args[0]["property_token"] == LUMEN_TOKEN
    res = r.json()
    assert res["check_status"] == "checked"
    note = res["notification"]
    assert note["kind"] == "hotel_drop"
    assert note["title"] == (
        "🏨 Lumen Hotel & The Lisbon Light Show dropped to $322 for 10–14 Dec (−$46)"
    )
    assert "$80.50 a night" in note["body"]  # cents under 100, as the UI
    assert note["data"]["watch_kind"] == "hotel"
    assert note["data"]["links"]["book"] == "https://www.lumenhotel.pt/"
    assert res["last_price"] == 322.0 and res["lowest_price"] == 322.0
    assert [p["price"] for p in res["history"]] == [368.0, 322.0]

    [smtp] = FakeSMTP.instances
    [msg] = smtp.sent
    assert msg["Subject"] == note["title"]
    text = msg.get_body(("plain",)).get_content()
    assert "Hotel price watch" in msg.get_body(("html",)).get_content()
    assert "$368 → $322" in text
    assert "the total for 4 nights, 2 guests ($80.50 a night)" in text
    assert "Lumen Hotel & The Lisbon Light Show · 10–14 Dec · 2 guests · 1 room" in text
    assert "https://www.lumenhotel.pt/" in text
    assert notifications_db.list_notifications(u["id"])["items"][0]["emailed_at"]


def test_check_now_target_copy(client):
    _, h = _user()
    w = _create_lumen(client, h, alert_mode="below_target", target_price=360)
    with serp(lumen_at(352, 88)):
        res = client.post(f"/api/price-watches/{w['id']}/check", headers=h).json()
    assert res["notification"]["kind"] == "hotel_target"
    assert res["notification"]["title"] == (
        "🏨 Lumen Hotel & The Lisbon Light Show is now $352 — below your $360 target"
    )


def test_sold_out_looks_never_alert_and_pause_after_three(client):
    _, h = _user()
    w = _create_lumen(client, h)
    no_rates = load("property_details_no_rates.json")
    no_rates["property_token"] = LUMEN_TOKEN
    statuses = []
    for _ in range(3):
        get_cache().clear()
        with serp(no_rates):
            res = client.post(f"/api/price-watches/{w['id']}/check", headers=h).json()
        statuses.append(res["check_status"])
        assert (
            res["notification"] is None or res["notification"]["kind"] == "watch_error"
        )
    assert statuses == ["unavailable", "unavailable", "errored"]
    assert res["status"] == "error"
    assert res["last_observation"]["status"] == "unavailable"
    assert res["last_price"] == 368.0  # never overwritten by a sold-out look
    assert res["problem"] == "Not available for your dates in the last few checks."


def test_check_now_failure_is_recorded_not_raised(client):
    _, h = _user()
    w = _create_lumen(client, h)
    with patch.object(
        hotel_prices,
        "_call",
        AsyncMock(side_effect=hotel_prices.SerpAPIError("HTTP 500")),
    ):
        res = client.post(f"/api/price-watches/{w['id']}/check", headers=h).json()
    assert res["check_status"] == "failed"
    assert res["status"] == "active"


# ── Scheduler ─────────────────────────────────────────────────────────────────


async def test_scheduler_checks_due_hotel_watches(client):
    u, h = _user()
    w = _create_lumen(client, h)
    with get_connection() as conn:  # only this watch is due
        conn.execute(
            "UPDATE price_watches SET status = 'paused' WHERE id != ?", (w["id"],)
        )
    later = NOW + timedelta(hours=25)  # past the 12 h ± jitter cadence
    with serp(lumen_at(340, 85)) as call:
        outcomes = await price_watch.run_due(
            "test-key", clock=lambda: later, rand=lambda: 0.5
        )
    assert call.await_count == 1
    [outcome] = [o for o in outcomes if o]
    assert outcome.status == "checked"
    assert outcome.notification["kind"] == "hotel_drop"
    assert outcome.notification["title"].startswith(
        "🏨 Lumen Hotel & The Lisbon Light Show dropped to $340"
    )
    stored = price_watch_db.get_watch(w["id"])
    assert stored["last_price"] == 340.0 and stored["check_count"] == 2
    assert fare_watch_db.calls_used(later.date().isoformat()) >= 1


async def test_scheduler_expires_on_check_in_day(client):
    _, h = _user()
    w = _create_lumen(client, h)
    with get_connection() as conn:
        conn.execute(
            "UPDATE price_watches SET status = 'paused' WHERE id != ?", (w["id"],)
        )
    on_check_in = datetime(2026, 12, 10, 8, 0, tzinfo=UTC)
    with serp() as call:
        outcomes = await price_watch.run_due(
            "test-key", clock=lambda: on_check_in, rand=lambda: 0.5
        )
    assert call.await_count == 0
    [outcome] = [o for o in outcomes if o]
    assert outcome.status == "expired"
    assert outcome.notification["kind"] == "watch_expired"
    assert outcome.notification["data"]["watch_kind"] == "hotel"


def test_failed_price_look_after_a_find_charges_both_calls(client):
    _, h = _user()
    with patch.object(
        hotel_prices,
        "_call",
        AsyncMock(
            side_effect=[
                load("named_search_lumen_single_property.json"),
                hotel_prices.SerpAPIError("HTTP 500"),
            ]
        ),
    ):
        r = _create(client, h)
    assert r.status_code == 502
    assert fare_watch_db.calls_used(NOW.date().isoformat()) == 2


# ── Final fix 2 ───────────────────────────────────────────────────────────────


def test_same_property_under_another_name_is_already_watched(client):
    """Two cards (or a "Not this one?" pick) that land on the same Google
    property, stay, guests and rooms share one watch (M2)."""
    u, h = _user()
    first = _create_lumen(client, h)
    with serp(
        load("named_search_lumen_single_property.json"),
        load("property_details_lumen_generic_q.json"),
    ):
        r = _create(client, h, _hotel(name="Lumen Hotel & The Lisbon Light Show"))
    assert r.status_code == 200, r.text
    assert r.json()["already_watching"] is True and r.json()["id"] == first["id"]
    with serp(load("property_details_lumen_generic_q.json")):
        picked = _create(client, h, _hotel(property_token=LUMEN_TOKEN))
    assert picked.json()["already_watching"] is True
    assert picked.json()["id"] == first["id"]
    assert len(price_watch_db.list_watches(u["id"], "hotel")) == 1


def test_same_property_for_other_guests_or_dates_is_a_new_watch(client):
    u, h = _user()
    _create_lumen(client, h)
    with serp(
        load("named_search_lumen_single_property.json"),
        load("property_details_lumen_generic_q.json"),
    ):
        r = _create(client, h, _hotel(name="Lumen Hotel Lisboa", adults=3))
    assert r.status_code == 200, r.text
    assert r.json()["already_watching"] is False
    assert len(price_watch_db.list_watches(u["id"], "hotel")) == 2


def test_hotel_watch_keeps_only_the_callers_own_plan_id(client):
    """A plan id is stored only when it is the caller's plan (M1)."""
    from app.db.plans_db import save_plan

    alice, ha = _user()
    bob, hb = _user()
    own = save_plan(alice["username"], "Lisbon", {}, {})
    other = save_plan(bob["username"], "Bob's", {}, {})
    w = _create_lumen(client, ha, plan_id=own["id"])
    assert w["plan_id"] == own["id"]
    w2 = _create_lumen(client, hb, plan_id=own["id"])  # alice's plan
    assert w2["plan_id"] is None
    w3 = _create_lumen(
        client, ha, hotel=_hotel(adults=3, plan_id=other["id"])
    )  # bob's plan, inside the spec
    assert w3["plan_id"] is None


# ── Check now skips the 30-minute cache (E2E finding O6) ──────────────────────


def _create_lumen_keep_cache(client, h, **over):
    with serp(
        load("named_search_lumen_single_property.json"),
        load("property_details_lumen_generic_q.json"),
    ):
        r = _create(client, h, **over)
    assert r.status_code == 200, r.text
    return r.json()  # the $368 look stays in the shared cache


def test_check_now_goes_live_despite_a_cached_look(client):
    _, h = _user()
    w = _create_lumen_keep_cache(client, h)
    assert hotel_prices.price_is_cached(LUMEN_TOKEN, "2026-12-10", "2026-12-14", 2)
    day = NOW.date().isoformat()
    used = fare_watch_db.calls_used(day)
    with serp(lumen_at(322, 80.5)) as call:
        res = client.post(f"/api/price-watches/{w['id']}/check", headers=h).json()
    assert call.await_count == 1  # live, not the cached $368
    assert res["check_status"] == "checked"
    assert res["last_price"] == 322.0
    assert res["notification"]["kind"] == "hotel_drop"
    assert fare_watch_db.calls_used(day) == used + 1  # charged as any live look


async def test_check_now_refreshes_the_cache_for_scheduled_checks(client):
    _, h = _user()
    w = _create_lumen_keep_cache(client, h)
    with serp(lumen_at(322, 80.5)):
        client.post(f"/api/price-watches/{w['id']}/check", headers=h)
    # A scheduled look within the cache TTL reuses the fresh answer: free
    day = NOW.date().isoformat()
    used = fare_watch_db.calls_used(day)
    with get_connection() as conn:
        conn.execute(
            "UPDATE price_watches SET next_check_at = ? WHERE id = ?",
            (NOW.isoformat(), w["id"]),
        )
    assert price_watch_db.claim_watch(w["id"], NOW, NOW + price_watch.LEASE)
    with serp() as call:
        outcome = await price_watch.check_watch(
            w["id"], now=NOW, api_key="test-key", rand=lambda: 0.5
        )
    assert call.await_count == 0
    assert outcome.status == "checked"
    assert price_watch_db.get_watch(w["id"])["last_price"] == 322.0
    assert fare_watch_db.calls_used(day) == used


def test_check_now_out_of_budget_spends_nothing_even_with_a_cached_look(
    client, monkeypatch
):
    _, h = _user()
    w = _create_lumen_keep_cache(client, h)
    day = NOW.date().isoformat()
    monkeypatch.setattr(
        settings, "fare_watch_daily_call_budget", fare_watch_db.calls_used(day)
    )
    with serp() as call:
        r = client.post(f"/api/price-watches/{w['id']}/check", headers=h)
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert call.await_count == 0
    assert price_watch_db.get_watch(w["id"])["last_price"] == 368.0
