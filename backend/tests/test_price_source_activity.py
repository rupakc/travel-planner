"""Activity price watches: the ``activity`` price source (GetYourGuide /
Viator prices as Google shows them) and its path through the price-watch
API, the scheduler and the alert email.

Offline: SerpAPI answers come from the sanitized fixtures recorded for
``activity_prices`` (tests/fixtures/serpapi/activities/), served through a
stubbed HTTP client.
"""

import copy
import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.auth import create_access_token
from app.core.cache import get_cache
from app.core.config import settings
from app.db import price_watch_db
from app.db.database import get_connection
from app.db.users_db import create_user
from app.services import alert_email, fare_watch, price_watch
from app.services.price_sources import activity as act
from app.services.price_watch import (
    CreatedWatch,
    InvalidSpec,
    NoLivePrice,
    PriceObservation,
)

FIXTURES = Path(__file__).parent / "fixtures" / "serpapi" / "activities"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
KEY = "sk-test-secret-key"

WALK = "Small Group Walking Tour of Belém"
WALK_URL = (
    "https://www.getyourguide.com/lisbon-l42/small-group-walking-tour-of-belem-t78184"
)
JERONIMOS_URL = (
    "https://www.getyourguide.com/lisbon-l42/"
    "jeronimos-monastery-entry-ticket-with-audio-guide-t1374987"
)
CATEGORY_URL = "https://www.getyourguide.com/belem-tower-l3590/culture-history-tc27"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _with_price(data: dict, url_part: str, price=None, currency=None) -> dict:
    """A copy of a fixture with one result's snippet price changed (or the
    result removed when ``price`` is "drop")."""
    data = copy.deepcopy(data)
    results = data["organic_results"]
    for i, item in enumerate(results):
        if url_part in item.get("link", ""):
            if price == "drop":
                del results[i]
                break
            det = item["rich_snippet"]["top"]["detected_extensions"]
            if price is not None:
                det["price"] = price
            if currency is not None:
                det["currency"] = currency
            item["rich_snippet"]["top"].pop("extensions", None)
            break
    else:
        raise AssertionError(f"{url_part} not in fixture")
    return data


@contextmanager
def serp(*responses):
    """Stub the shared SerpAPI client (under its private and public names, so
    the stub survives the adapters switching to the public helper)."""
    side = [
        httpx.Response(200, json=r) if isinstance(r, dict) else r for r in responses
    ]
    client = AsyncMock()
    client.get = AsyncMock(side_effect=side)
    with (
        patch("app.services.serp_flights._get_client", return_value=client),
        patch(
            "app.services.serp_flights.get_serp_client",
            return_value=client,
            create=True,
        ),
    ):
        yield client


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    get_cache().clear()
    monkeypatch.setattr(fare_watch, "utcnow", lambda: NOW)
    yield
    get_cache().clear()


def _spec(**over):
    spec = {"name": WALK, "city": "Lisbon", "travellers": 2}
    spec.update(over)
    return spec


USER = {"id": "u-1"}


# ── Spec validation and match key ────────────────────────────────────────────


class TestSpec:
    def test_match_key_is_normalised_name_city_date_travellers(self):
        a = act.SOURCE.match_key(_spec(date="2026-12-10"))
        b = act.SOURCE.match_key(
            {
                "name": "  small group WALKING tour of Belem ",
                "city": "lisbon",
                "date": "2026-12-10",
                "travellers": 2,
                "estimate_price": 30,
            }
        )
        assert a == b == "small group walking tour of belem|lisbon|2"

    def test_a_picked_listing_is_its_own_subject(self):
        # A suggestion the traveller picked instead is a different subject:
        # the activity card itself stays unwatched.
        own = act.SOURCE.match_key(_spec())
        picked = act.SOURCE.match_key(_spec(listing_url=WALK_URL + "?ranking=1"))
        assert picked == f"{own}|{WALK_URL}"

    def test_match_key_differs_by_travellers_not_date(self):
        # the date only sets expires_on: it changes as the itinerary moves
        assert act.SOURCE.match_key(_spec()) != act.SOURCE.match_key(
            _spec(travellers=3)
        )
        assert act.SOURCE.match_key(_spec()) == act.SOURCE.match_key(
            _spec(date="2026-12-10")
        )

    def test_travellers_default_to_one(self):
        assert act.SOURCE.match_key({"name": "Tour", "city": "Rome"}).endswith("|1")

    @pytest.mark.parametrize(
        "spec",
        [
            {"city": "Lisbon"},
            {"name": "  ", "city": "Lisbon"},
            {"name": "Tour"},
            {"name": "x" * 201, "city": "Lisbon"},
            {"name": "Tour", "city": "Lisbon", "travellers": 0},
            {"name": "Tour", "city": "Lisbon", "travellers": 21},
            {"name": "Tour", "city": "Lisbon", "travellers": True},
            {"name": "Tour", "city": "Lisbon", "travellers": "2"},
            {"name": "Tour", "city": "Lisbon", "date": "10/12/2026"},
            {"name": "Tour", "city": "Lisbon", "date": "2026-11-04"},  # today
            {"name": "Tour", "city": "Lisbon", "date": "2026-01-01"},
            {"name": "Tour", "city": "Lisbon", "listing_url": "https://evil.test/x"},
            {"name": "Tour", "city": "Lisbon", "listing_url": CATEGORY_URL},
            {"name": "Tour", "city": "Lisbon", "estimate_price": -3},
            {"name": "Tour", "city": "Lisbon", "estimate_price": "cheap"},
        ],
    )
    def test_invalid_specs(self, spec):
        with pytest.raises(InvalidSpec):
            act.SOURCE.match_key(spec)

    def test_estimate_calls_is_one(self):
        assert act.SOURCE.estimate_calls({"subject": {}}) == 1


# ── Create ────────────────────────────────────────────────────────────────────


class TestCreate:
    async def test_matches_a_specific_listing_and_takes_the_baseline(self):
        with serp(_fixture("gyg_belem_tower")) as client:
            res = await act.SOURCE.create(_spec(), USER, KEY)
        assert isinstance(res, CreatedWatch)
        assert client.get.await_count == 1  # GetYourGuide matched: no Viator query
        assert res.title == WALK
        assert res.subtitle == "GetYourGuide · 2 travellers"
        assert res.currency == "USD"
        assert res.subject == {
            "name": WALK,
            "city": "Lisbon",
            "listing_url": WALK_URL,
            "listing_title": WALK,
            "provider": "getyourguide",
            "query": f"{WALK} Lisbon getyourguide",
            "travellers": 2,
            "currency": "USD",
            "date": None,
        }
        b = res.baseline
        assert (b.price, b.unit_price, b.status) == (66.92, 33.46, "ok")
        assert b.source == "getyourguide_via_google"
        assert b.link == WALK_URL
        assert b.calls == 1
        assert b.observed["rating"] == 4.9 and b.observed["reviews"] == 80
        assert b.observed["source"] == "getyourguide_via_google"
        assert b.observed["observed_at"]
        assert b.observed["listing_title"] == WALK
        assert res.expires_on == (NOW.date() + timedelta(days=180)).isoformat()

    async def test_the_activity_date_ends_the_watch(self):
        with serp(_fixture("gyg_belem_tower")):
            res = await act.SOURCE.create(
                _spec(date="2026-12-10", travellers=1), USER, KEY
            )
        assert res.expires_on == "2026-12-10"
        assert res.subject["date"] == "2026-12-10"
        assert res.subtitle == "GetYourGuide · 1 traveller"
        assert res.baseline.price == 33.46

    async def test_cached_search_spends_no_calls(self):
        with serp(_fixture("gyg_belem_tower")):
            await act.SOURCE.create(_spec(), USER, KEY)
            again = await act.SOURCE.create(_spec(travellers=1), USER, KEY)
        assert again.baseline.calls == 0

    async def test_category_page_is_not_watchable_and_offers_listings(self):
        # "Belem Tower tour" only matches a category page ("The best Belem
        # Tower Culture & history", from $11.63): never watched.
        viator = {"organic_results": []}
        with serp(_fixture("gyg_belem_tower"), viator) as client:
            res = await act.SOURCE.create(
                _spec(name="Belem Tower tour", estimate_price=25), USER, KEY
            )
        assert isinstance(res, NoLivePrice)
        assert client.get.await_count == 2  # Viator tried too
        assert res.calls == 2
        assert res.message == (
            "We couldn't find a live price for this activity on GetYourGuide or Viator."
        )
        assert res.estimate == {
            "price": 25.0,
            "source": "ai_estimate",
            "currency": "USD",
            "label": "per person",
        }
        assert 1 <= len(res.suggestions) <= 3
        for s in res.suggestions:
            assert "-t" in s["link"]  # specific activity pages only
            assert s["spec"]["listing_url"] == s["link"]
            assert s["spec"]["name"] == "Belem Tower tour"
            assert s["spec"]["travellers"] == 2
            assert s["currency"] == "USD"
            assert s["subtitle"].startswith("GetYourGuide · ")
            assert "per person" in s["subtitle"]
        first = res.suggestions[0]
        assert first["title"].startswith("Jerónimos Monastery")
        assert first["price"] == 22.87

    async def test_no_priced_listing_at_all(self):
        with serp(_fixture("gyg_no_priced"), _fixture("viator_belem_tower")):
            res = await act.SOURCE.create(
                _spec(name="Biblioteca Nacional reading room"), USER, KEY
            )
        assert isinstance(res, NoLivePrice)
        assert res.suggestions == []  # the only priced result is a category page
        assert res.estimate is None

    async def test_picked_suggestion_prices_that_listing(self):
        spec = _spec(name="Belem Tower tour", listing_url=JERONIMOS_URL)
        with serp(_fixture("gyg_belem_tower")) as client:
            res = await act.SOURCE.create(spec, USER, KEY)
        assert client.get.await_count == 1
        assert isinstance(res, CreatedWatch)
        assert res.subject["name"] == "Belem Tower tour"
        assert res.subject["listing_url"] == JERONIMOS_URL
        assert res.title.startswith("Jerónimos Monastery")
        assert res.baseline.unit_price == 22.87
        assert res.baseline.price == 45.74

    async def test_picked_suggestion_that_vanished(self):
        data = _with_price(_fixture("gyg_belem_tower"), "t1374987", "drop")
        spec = _spec(name="Belem Tower tour", listing_url=JERONIMOS_URL)
        with serp(data):
            res = await act.SOURCE.create(spec, USER, KEY)
        assert isinstance(res, NoLivePrice)
        assert all(s["link"] != JERONIMOS_URL for s in res.suggestions)

    async def test_non_usd_listing_keeps_its_currency(self):
        data = _with_price(_fixture("gyg_belem_tower"), "t78184", 30.5, "€")
        with serp(data):
            res = await act.SOURCE.create(_spec(), USER, KEY)
        assert res.currency == "EUR" and res.subject["currency"] == "EUR"
        assert res.baseline.price == 61.0
        assert res.subtitle == "GetYourGuide · 2 travellers"

    async def test_serpapi_errors_propagate_with_the_calls_spent(self):
        with serp(httpx.Response(500, text="boom")), pytest.raises(Exception) as e:
            await act.SOURCE.create(_spec(), USER, KEY)
        assert e.value.calls == 0
        # GetYourGuide answered (category only), then Viator failed: 1 spent
        with (
            serp(_fixture("gyg_belem_tower"), httpx.Response(500, text="boom")),
            pytest.raises(Exception) as e,
        ):
            await act.SOURCE.create(_spec(name="Belem Tower tour"), USER, KEY)
        assert e.value.calls == 1

    async def test_check_spends_nothing_when_cached(self):
        with serp(_fixture("gyg_belem_tower")):
            first = await act.SOURCE.check(_watch(), KEY)
            again = await act.SOURCE.check(_watch(), KEY)
        assert (first.calls, again.calls) == (1, 0)


# ── Check ─────────────────────────────────────────────────────────────────────


def _watch(**subject_over):
    subject = {
        "name": WALK,
        "city": "Lisbon",
        "listing_url": WALK_URL,
        "listing_title": WALK,
        "provider": "getyourguide",
        "query": f"{WALK} Lisbon getyourguide",
        "travellers": 2,
        "currency": "USD",
        "date": None,
    }
    subject.update(subject_over)
    return {"id": 1, "kind": "activity", "subject": subject, "currency": "USD"}


class TestCheck:
    async def test_prices_the_stored_listing(self):
        data = _with_price(_fixture("gyg_belem_tower"), "t78184", 29.0)
        with serp(data) as client:
            obs = await act.SOURCE.check(_watch(), KEY)
        assert client.get.await_count == 1
        assert (obs.status, obs.price, obs.unit_price) == ("ok", 58.0, 29.0)
        assert obs.calls == 1
        assert obs.link == WALK_URL
        assert obs.observed["rating"] == 4.9
        assert obs.observed["matched_by"] == "url"

    async def test_listing_gone_is_unavailable(self):
        data = _with_price(_fixture("gyg_belem_tower"), "t78184", "drop")
        with serp(data):
            obs = await act.SOURCE.check(_watch(), KEY)
        assert (obs.status, obs.price) == ("unavailable", None)
        assert obs.observed["reason"] == "not_found"

    async def test_listing_without_a_price_is_unavailable(self):
        data = copy.deepcopy(_fixture("gyg_belem_tower"))
        for item in data["organic_results"]:
            if "t78184" in item["link"]:
                item.pop("rich_snippet", None)
                item["snippet"] = "A great walk."
        with serp(data):
            obs = await act.SOURCE.check(_watch(), KEY)
        assert obs.status == "unavailable"
        assert obs.observed["reason"] == "no_price"

    async def test_currency_change_is_unavailable_never_a_price(self):
        data = _with_price(_fixture("gyg_belem_tower"), "t78184", 20.0, "€")
        with serp(data):
            obs = await act.SOURCE.check(_watch(), KEY)
        assert (obs.status, obs.price) == ("unavailable", None)
        assert obs.observed["reason"] == "currency_changed"
        assert obs.observed["seen_currency"] == "EUR"

    async def test_errors_raise(self):
        with (
            serp(httpx.Response(429, text="slow down")),
            pytest.raises(Exception) as exc,
        ):
            await act.SOURCE.check(_watch(), KEY)
        assert getattr(exc.value, "quota_exceeded", False)


# ── Wording ───────────────────────────────────────────────────────────────────


class TestCompose:
    def _w(self, **kw):
        w = _watch()
        w.update({"title": WALK, "target_price": None, **kw})
        w["subject"]["name"] = "Belém walking tour"
        w["subject"]["listing_title"] = "Belém Walking Tour"  # same activity
        w["subject"]["travellers"] = 1
        return w

    def test_drop(self):
        obs = PriceObservation(price=9.9, unit_price=9.9, source="x")
        note = act.SOURCE.compose("activity_drop", self._w(), obs, 11.63)
        assert note["title"] == (
            "🎟️ Belém walking tour is now from $9.90 per person (−$1.73)"
        )
        assert "GetYourGuide" in note["body"]
        assert note["data"]["unit_price"] == 9.9
        assert note["data"]["currency"] == "USD"

    def test_drop_for_several_travellers_explains_the_total(self):
        w = self._w()
        w["subject"]["travellers"] = 2
        obs = PriceObservation(price=19.8, unit_price=9.9, source="x")
        note = act.SOURCE.compose("activity_drop", w, obs, 23.26)
        assert note["title"].endswith("from $9.90 per person (−$1.73)")
        assert "$19.80 for 2 travellers" in note["body"]

    def test_target(self):
        w = self._w(target_price=10.0)
        obs = PriceObservation(price=9.9, unit_price=9.9, source="x")
        note = act.SOURCE.compose("activity_target", w, obs, 11.63)
        assert note["title"] == (
            "🎟️ Belém walking tour is under your target: from $9.90 per person"
        )
        assert "$10" in note["body"]

    def test_euro_wording(self):
        w = self._w()
        w["subject"]["currency"] = w["currency"] = "EUR"
        obs = PriceObservation(price=9.9, unit_price=9.9, source="x")
        note = act.SOURCE.compose("activity_drop", w, obs, 11.63)
        assert note["title"].endswith("from €9.90 per person (−€1.73)")


# ── Through the API, the scheduler and email ──────────────────────────────────


@pytest.fixture
def api(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    monkeypatch.setattr(settings, "serpapi_key", KEY)
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 200)
    monkeypatch.setattr(settings, "fare_watch_max_active_per_user", 10)
    with get_connection() as conn:
        conn.execute("DELETE FROM fare_watch_quota")
        conn.execute("DELETE FROM fare_watch_user_quota")
    price_watch.register_source(act.SOURCE)
    tag = uuid.uuid4().hex[:8]
    u = create_user(f"pwa-{tag}", "pw-123456789", email=f"{tag}@example.test")
    token = create_access_token({"sub": u["username"]})
    return client, u, {"Authorization": f"Bearer {token}"}


def _post(client, h, spec, **over):
    body = {"kind": "activity", "activity": spec, **over}
    return client.post("/api/price-watches", json=body, headers=h)


def test_activity_source_is_a_builtin():
    assert "app.services.price_sources.activity" in price_watch.SOURCE_MODULES
    assert isinstance(act.SOURCE, price_watch.PriceSource)
    assert act.SOURCE.kind == "activity"


class TestApi:
    def test_create_then_already_watching_and_match(self, api):
        client, u, h = api
        with serp(_fixture("gyg_belem_tower")) as http:
            r = _post(client, h, _spec())
            assert r.status_code == 200, r.text
            w = r.json()
            again = _post(client, h, _spec(estimate_price=30))
        assert http.get.await_count == 1
        assert "api_key" not in json.dumps(w)
        assert w["kind"] == "activity" and w["already_watching"] is False
        assert w["currency"] == "USD"
        assert (w["baseline_price"], w["last_observation"]["unit_price"]) == (
            66.92,
            33.46,
        )
        assert w["link"] == WALK_URL
        assert w["subject"]["listing_title"] == WALK
        assert again.json()["already_watching"] is True
        assert again.json()["id"] == w["id"]
        m = client.post(
            "/api/price-watches/match",
            json={"kind": "activity", "activity": _spec()},
            headers=h,
        )
        assert m.json()["watch"]["id"] == w["id"]

    def test_invalid_spec_is_422(self, api):
        client, _, h = api
        r = _post(client, h, {"name": "Tour", "city": "Lisbon", "travellers": 50})
        assert r.status_code == 422
        assert "travellers" in r.json()["detail"].lower()

    def test_no_live_price_returns_suggestions(self, api):
        client, _, h = api
        with serp(_fixture("gyg_belem_tower"), {"organic_results": []}):
            r = _post(client, h, _spec(name="Belem Tower tour", estimate_price=25))
        assert r.status_code == 422
        body = r.json()
        assert body["code"] == "no_live_price"
        assert body["estimate"]["source"] == "ai_estimate"
        pick = body["suggestions"][0]
        with serp():  # cached: the pick spends nothing
            r2 = _post(client, h, pick["spec"])
        assert r2.status_code == 200, r2.text
        assert r2.json()["subject"]["listing_url"] == pick["link"]
        m = client.post(
            "/api/price-watches/match",
            json={"kind": "activity", "activity": _spec(name="Belem Tower tour")},
            headers=h,
        )
        assert m.json()["watch"] is None  # the card's own subject stays unwatched

    def test_check_now_drop_and_currency_change(self, api):
        client, u, h = api
        with serp(_fixture("gyg_belem_tower")):
            w = _post(client, h, _spec()).json()
        get_cache().clear()
        cheaper = _with_price(_fixture("gyg_belem_tower"), "t78184", 20.0)
        with serp(cheaper):
            r = client.post(f"/api/price-watches/{w['id']}/check", headers=h)
        res = r.json()
        assert res["check_status"] == "checked", r.text
        assert res["last_price"] == 40.0
        note = res["notification"]
        assert note["kind"] == "activity_drop"
        assert note["title"] == (
            "🎟️ Small Group Walking Tour of Belém is now from $20 per person (−$13.46)"
        )
        assert note["data"]["watch_kind"] == "activity"
        assert note["data"]["links"]["book"] == WALK_URL

        get_cache().clear()
        euros = _with_price(_fixture("gyg_belem_tower"), "t78184", 15.0, "€")
        with serp(euros):
            r = client.post(f"/api/price-watches/{w['id']}/check", headers=h)
        res = r.json()
        assert res["check_status"] == "unavailable"
        assert res["last_price"] == 40.0  # never compared across currencies
        assert res["notification"] is None

    def test_listing_gone_is_unavailable(self, api):
        client, _, h = api
        with serp(_fixture("gyg_belem_tower")):
            w = _post(client, h, _spec()).json()
        get_cache().clear()
        with serp(_with_price(_fixture("gyg_belem_tower"), "t78184", "drop")):
            r = client.post(f"/api/price-watches/{w['id']}/check", headers=h)
        assert r.json()["check_status"] == "unavailable"
        assert r.json()["last_observation"]["observed"]["reason"] == "not_found"

    async def test_scheduler_checks_and_emails_with_the_listing_currency(
        self, api, monkeypatch
    ):
        client, u, h = api
        data = _with_price(_fixture("gyg_belem_tower"), "t78184", 40.0, "€")
        with serp(data):
            w = _post(client, h, _spec(), email_enabled=False).json()
        assert w["currency"] == "EUR"
        assert w["subtitle"] == "GetYourGuide · 2 travellers"
        price_watch_db.update_watch(
            w["id"],
            email_enabled=True,
            next_check_at=(NOW - timedelta(minutes=1)).isoformat(),
        )
        with get_connection() as conn:  # only this watch is due
            conn.execute(
                "UPDATE price_watches SET status = 'paused' WHERE id != ?", (w["id"],)
            )
        monkeypatch.setattr(settings, "smtp_host", "smtp.test")
        sent = []
        monkeypatch.setattr(alert_email, "send_message", sent.append)
        get_cache().clear()
        cheaper = _with_price(_fixture("gyg_belem_tower"), "t78184", 30.0, "€")
        later = NOW + timedelta(hours=13)
        with serp(cheaper):
            outcomes = await price_watch.run_due(
                KEY, clock=lambda: later, rand=lambda: 0.5
            )
        done = [o for o in outcomes if o and o.watch and o.watch["id"] == w["id"]]
        assert done and done[0].status == "checked"
        note = done[0].notification
        assert note["title"] == (
            "🎟️ Small Group Walking Tour of Belém is now from €30 per person (−€10)"
        )
        assert len(sent) == 1
        msg = sent[0]
        assert msg["Subject"] == note["title"]
        text = msg.get_body(("plain",)).get_content()
        assert "Activity price watch" not in text  # eyebrow is HTML only
        assert "€80 → €60" in text
        assert "$" not in text.split("Price:")[1].splitlines()[0]
        html = msg.get_body(("html",)).get_content()
        assert "Activity price watch" in html and "See activity" in html
        assert note["kind"] == "activity_drop"
        assert note["data"]["watch_kind"] == "activity"


# ── Prices in their own currency (core helper) ───────────────────────────────


@pytest.mark.parametrize(
    "amount,currency,text",
    [
        (9.9, "USD", "$9.90"),
        (33.456, "USD", "$33.46"),
        (398.0, "USD", "$398"),
        (46.0, "USD", "$46"),
        (40.0, "EUR", "€40"),
        (1240.4, "USD", "$1,240"),
        (9.9, "EUR", "€9.90"),
        (12.5, "eur", "€12.50"),
        (1500, "JPY", "¥1,500"),
        (77.48, "AUD", "A$77.48"),
        (12.5, "CHF", "12.50 CHF"),
        (12.5, None, "$12.50"),
    ],
)
def test_format_price(amount, currency, text):
    assert price_watch.format_price(amount, currency) == text


def test_expiry_notice_uses_the_watch_currency():
    note = price_watch._expired_note(
        {
            "id": 7,
            "kind": "activity",
            "title": WALK,
            "expires_on": "2026-12-10",
            "lowest_price": 59.0,
            "currency": "EUR",
        }
    )
    assert note["body"].endswith("The lowest price we saw was €59.")


# ── Fix round 1 ──────────────────────────────────────────────────────────────


class TestActivityStep:
    """Activities alert on small drops: max(1 unit of the listing currency, 5 %)."""

    def test_source_uses_the_activity_step(self):
        from app.services import price_rules

        assert price_rules.ACTIVITY_STEP == price_rules.Step(min_usd=1.0, min_pct=0.05)
        assert price_watch.step_for(act.SOURCE) is price_rules.ACTIVITY_STEP

    def _watch(self):
        return {
            "id": 3,
            "kind": "activity",
            "title": WALK,
            "subtitle": None,
            "alert_mode": "any_drop",
            "target_price": None,
            "baseline_price": 23.26,
            "last_notified_price": None,
            "own_peak_price": None,
            "lowest_price": 23.26,
            "check_count": 1,
            "currency": "EUR",
            "subject": {**_watch()["subject"], "travellers": 2, "currency": "EUR"},
        }

    def test_a_173_drop_per_person_alerts(self):
        obs = PriceObservation(price=19.8, unit_price=9.9, source="x")
        note = price_watch.evaluate(self._watch(), obs, NOW, act.SOURCE)
        assert note and note["kind"] == "activity_drop"
        assert note["title"].endswith("from €9.90 per person (−€1.73)")

    def test_a_50_cent_drop_does_not(self):
        obs = PriceObservation(price=22.76, unit_price=11.38, source="x")
        assert price_watch.evaluate(self._watch(), obs, NOW, act.SOURCE) is None


class TestPickedSuggestionWording:
    def test_title_names_the_listing_and_body_the_ai_name(self):
        w = _watch(name="Belém walking tour", listing_title="Jerónimos Monastery Entry")
        w.update(title="Jerónimos Monastery Entry", target_price=None)
        w["subject"]["travellers"] = 1
        obs = PriceObservation(price=9.9, unit_price=9.9, source="x")
        note = act.SOURCE.compose("activity_drop", w, obs, 11.63)
        assert note["title"] == (
            "🎟️ Jerónimos Monastery Entry is now from $9.90 per person (−$1.73)"
        )
        assert "for your ‘Belém walking tour’" in note["body"]

    def test_same_name_keeps_the_simple_wording(self):
        w = _watch(name="small group walking tour of belem")
        w.update(title=WALK, target_price=None)
        obs = PriceObservation(price=19.8, unit_price=9.9, source="x")
        note = act.SOURCE.compose("activity_drop", w, obs, 23.26)
        assert note["title"].startswith("🎟️ small group walking tour of belem is now")
        assert "for your" not in note["body"]


class TestPickQuery:
    async def test_pick_reuses_the_cached_query_that_listed_it(self):
        # A Viator listing surfaced by the GetYourGuide query: picking it
        # re-reads that cached query instead of spending a Viator search.
        viator_url = "https://www.viator.com/tours/Lisbon/Belem-Walk/d538-88037P242"
        data = copy.deepcopy(_fixture("gyg_belem_tower"))
        data["organic_results"].insert(
            0,
            {
                "position": 1,
                "link": viator_url,
                "title": "Belém Walking Tour",
                "rich_snippet": {
                    "top": {"detected_extensions": {"price": 25.0, "currency": "$"}}
                },
            },
        )
        with serp(data, {"organic_results": []}) as client:
            first = await act.SOURCE.create(_spec(name="Belem Tower tour"), USER, KEY)
            assert any(s["link"] == viator_url for s in first.suggestions)
            calls_before = client.get.await_count
            res = await act.SOURCE.create(
                _spec(name="Belem Tower tour", listing_url=viator_url), USER, KEY
            )
        assert isinstance(res, CreatedWatch)
        assert client.get.await_count == calls_before
        assert res.baseline.calls == 0
        assert res.subject["provider"] == "viator"
        assert res.subject["query"] == "Belem Tower tour Lisbon getyourguide"


class TestApiFixRound:
    def test_target_currency_mismatch_creates_nothing_and_retry_is_free(self, api):
        client, u, h = api
        data = _with_price(_fixture("gyg_belem_tower"), "t78184", 30.5, "€")
        body = {
            "alert_mode": "below_target",
            "target_price": 50,
            "target_currency": "USD",
        }
        with serp(data) as http:
            r = _post(client, h, _spec(), **body)
            assert r.status_code == 422, r.text
            j = r.json()
            assert j["code"] == "target_currency_mismatch"
            assert (j["currency"], j["price"], j["unit_price"]) == ("EUR", 61.0, 30.5)
            assert "EUR" in j["message"]
            assert (
                client.get(
                    "/api/price-watches", params={"kind": "activity"}, headers=h
                ).json()
                == []
            )
            used = http.get.await_count
            r2 = _post(
                client,
                h,
                _spec(),
                alert_mode="below_target",
                target_price=55,
                target_currency="EUR",
            )
            assert r2.status_code == 200, r2.text
            assert http.get.await_count == used  # cached: the retry spends nothing
        assert r2.json()["target_price"] == 55 and r2.json()["currency"] == "EUR"

    def test_any_drop_ignores_target_currency(self, api):
        client, _, h = api
        data = _with_price(_fixture("gyg_belem_tower"), "t78184", 30.5, "€")
        with serp(data):
            r = _post(client, h, _spec(), target_currency="USD")
        assert r.status_code == 200, r.text

    def test_same_listing_is_already_watched_whether_matched_or_picked(self, api):
        client, _, h = api
        # the second name is its own (uncached) query
        with serp(_fixture("gyg_belem_tower"), _fixture("gyg_belem_tower")):
            w = _post(client, h, _spec()).json()  # auto-matched WALK_URL
            picked = _post(
                client,
                h,
                _spec(name="Belem walking tour", listing_url=WALK_URL + "/?x=1"),
            )
            other_people = _post(
                client,
                h,
                _spec(name="Belem walking tour", listing_url=WALK_URL, travellers=3),
            )
        assert picked.status_code == 200, picked.text
        assert picked.json()["already_watching"] is True
        assert picked.json()["id"] == w["id"]
        assert other_people.json()["already_watching"] is False
        # /match stays name-based: the picking card's own name isn't watched
        m = client.post(
            "/api/price-watches/match",
            json={"kind": "activity", "activity": _spec(name="Belem walking tour")},
            headers=h,
        )
        assert m.json()["watch"] is None
