"""Whole-trip price watch source (``price_sources.trip``).

Unit tests stub the Phase-1 adapters (``fare_watch.fetch_fares``,
``hotel_prices``, ``activity_prices``) at module level; the API tests at the
bottom go through ``/api/price-watches`` with the real source registered and
only the SerpAPI HTTP client faked, answering from the recorded fixtures in
``tests/fixtures/serpapi/`` (flights: a small synthetic google_flights body).
No test touches the network.
"""

import asyncio
import copy
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.core.auth import create_access_token
from app.core.cache import get_cache
from app.core.config import settings
from app.db import notifications_db, price_watch_db
from app.db.database import get_connection
from app.db.plans_db import delete_plan, save_plan
from app.db.users_db import create_user
from app.services import (
    activity_prices,
    fare_watch,
    hotel_prices,
    price_rules,
    price_watch,
    serp_flights,
)
from app.services.activity_prices import ActivityListing, ActivityPrice
from app.services.fare_watch import FareCheck
from app.services.hotel_prices import HotelOffer, HotelPrice
from app.services.price_sources import trip
from app.services.price_watch import InvalidSpec, NoLivePrice, PriceObservation

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "serpapi"

SEARCH = {
    "origin": "Berlin",
    "destination": "Lisbon, Portugal",
    "departure_date": "2026-12-10",
    "return_date": "2026-12-14",
    "num_travelers": 2,
}
FLIGHT = {"airline": "TAP", "price_usd": 640.0, "trip_type": "round_trip"}
HOTEL = {"name": "Lumen Hotel", "price_per_night_usd": 110.0, "total_price_usd": 440.0}


def _acts(*names, price=30.0):
    return [{"name": n, "price_usd": price} for n in names]


SELECTIONS = {
    "flight": FLIGHT,
    "hotel": HOTEL,
    "activities": _acts("Jeronimos Monastery", "Small Group Walking Tour of Belem"),
    "sim": {"provider": "Airalo", "price_usd": 13.0},
    "getting_around": [{"mode": "Metro"}],
}


@pytest.fixture(autouse=True)
def _clean_cache():
    get_cache().clear()
    yield
    get_cache().clear()


def _user():
    return create_user(f"tr-{uuid.uuid4().hex[:8]}", "pw-123456789")


def _plan(user, selections=None, search=None, name="Lisbon escape"):
    return save_plan(
        user["username"],
        name,
        dict(SEARCH if search is None else search),
        copy.deepcopy(SELECTIONS if selections is None else selections),
    )


# ── Adapter stubs ─────────────────────────────────────────────────────────────


class Stubs:
    """Programmable fakes for the three adapters; records every call and,
    like the real adapters, caches every answer it "fetched" (the source
    counts SerpAPI calls by the cache entries a lookup fills)."""

    def __init__(self):
        self.fares: list = [612.0]  # FareCheck price (or exception) per call
        self.hotel_offers = [_offer("Lumen Hotel & The Lisbon Light Show", 398.0)]
        self.hotel_prices: list = []  # HotelPrice (or exception) per call
        self.listings = {  # activity name → listings returned by find_listings
            "Jeronimos Monastery": [_listing("Jeronimos Monastery Entry", 22.87)],
            "Small Group Walking Tour of Belem": [
                _listing("Small Group Walking Tour of Belém", 33.46)
            ],
        }
        self.activity_prices: dict = {}  # url → list of ActivityPrice / exc
        self.calls: list[tuple] = []

    async def fetch_fares(self, fw, api_key):
        self.calls.append(("flight", fw["origin_code"], fw["destination_code"]))
        item = self.fares.pop(0) if len(self.fares) > 1 else self.fares[0]
        if isinstance(item, Exception):
            raise item
        return FareCheck(price=item, calls=1)

    async def find_properties(self, name, city, ci, co, adults, api_key, rooms=1):
        self.calls.append(("hotel_find", name, city, ci, co, adults, rooms))
        q = f"{name} {city}"
        get_cache()[hotel_prices.find_cache_key(q, ci, co, adults, rooms)] = ()
        return list(self.hotel_offers)

    async def price_property(self, token, ci, co, adults, api_key, rooms=1, **kw):
        self.calls.append(("hotel_price", token))
        item = self.hotel_prices.pop(0)
        if isinstance(item, Exception):
            raise item
        get_cache()[hotel_prices.price_cache_key(token, ci, co, adults, rooms)] = item
        return item

    async def find_listings(self, name, city, api_key):
        self.calls.append(("activity_find", name, city))
        found = list(self.listings.get(name, []))
        cache = get_cache()
        for provider in ("getyourguide", "viator"):
            q = activity_prices.build_query(name, city, provider)
            cache[activity_prices.search_cache_key(q)] = {"results": []}
            best = activity_prices.match_listing(name, found, city)
            if best is not None and not best.is_category:
                break  # the Viator query only runs without a GYG match
        return found

    async def price_listing(self, listing, query, api_key):
        self.calls.append(("activity_price", listing.url))
        item = self.activity_prices[listing.url].pop(0)
        if isinstance(item, Exception):
            raise item
        get_cache()[activity_prices.search_cache_key(query)] = {"results": []}
        return item

    def count(self, kind):
        return sum(1 for c in self.calls if c[0] == kind)


def _offer(name, total, token="tok-lumen"):
    return HotelOffer(
        name=name,
        property_token=token,
        rate_per_night=total / 4,
        total_rate=total,
        currency="USD",
        hotel_class=4,
        overall_rating=4.4,
        reviews=900,
        link="https://www.google.com/travel/hotels/lumen",
        gps=None,
        check_in="2026-12-10",
        check_out="2026-12-14",
        adults=2,
    )


def _listing(title, price, currency="USD", kind="activity", slug=None):
    slug = slug or title.lower().replace(" ", "-")[:30]
    return ActivityListing(
        provider="getyourguide",
        url=f"https://www.getyourguide.com/lisbon-l42/{slug}",
        title=title,
        price_from=price,
        currency=currency,
        is_usd=currency == "USD",
        rating=4.6,
        reviews=1200,
        snippet="",
        page_kind=kind,
        query=f"{title} Lisbon getyourguide",
    )


def _hp(total, available=True):
    return HotelPrice(
        total=total if available else None,
        nightly=total / 4 if available else None,
        available=available,
        link="https://www.google.com/travel/hotels/lumen",
    )


def _ap(url, price, available=True, currency="USD"):
    return ActivityPrice(
        price_from=price if available else None,
        currency=currency if available else None,
        is_usd=currency == "USD" and available,
        available=available,
        url=url,
        observed="2026-11-04T12:00:00+00:00",
        source="getyourguide_via_google",
        reason=None if available else "not_found",
    )


@pytest.fixture
def stubs(monkeypatch, client):
    s = Stubs()
    monkeypatch.setattr(fare_watch, "fetch_fares", s.fetch_fares)
    monkeypatch.setattr(hotel_prices, "find_properties", s.find_properties)
    monkeypatch.setattr(hotel_prices, "price_property", s.price_property)
    monkeypatch.setattr(activity_prices, "find_listings", s.find_listings)
    monkeypatch.setattr(activity_prices, "price_listing", s.price_listing)
    return s


def run(coro):
    return asyncio.run(coro)


def _create(user, plan_id):
    return run(trip.SOURCE.create({"plan_id": plan_id}, user, "k"))


def _watch(created, watch_id=1, last=None):
    """A watch row as the pipeline hands it to ``check``."""
    obs = last or created.baseline
    return {
        "id": watch_id,
        "kind": "trip",
        "title": created.title,
        "subtitle": created.subtitle,
        "subject": created.subject,
        "baseline_price": created.baseline.price,
        "last_observation": {"breakdown": obs.breakdown, "status": obs.status},
        "reference_looks": {"baseline": created.baseline.breakdown},
    }


def _by_id(breakdown):
    return {c["id"]: c for c in breakdown}


# ── Protocol basics ───────────────────────────────────────────────────────────


def test_source_is_a_registered_price_source(client):
    assert isinstance(trip.SOURCE, price_watch.PriceSource)
    assert trip.SOURCE.kind == "trip"
    assert price_watch.get_source("trip") is trip.SOURCE
    assert "app.services.price_sources.trip" in price_watch.SOURCE_MODULES


def test_trip_step_is_max_25_or_4_percent():
    assert trip.SOURCE.step is price_rules.TRIP_STEP
    assert price_watch.step_for(trip.SOURCE)(500) == 25
    assert price_watch.step_for(trip.SOURCE)(2000) == 80


def test_match_key_is_the_plan():
    assert trip.SOURCE.match_key({"plan_id": 42}) == "plan:42"
    assert trip.SOURCE.match_key({"plan_id": "42"}) == "plan:42"
    for bad in ({}, {"plan_id": None}, {"plan_id": "x"}, {"plan_id": 0}):
        with pytest.raises(InvalidSpec):
            trip.SOURCE.match_key(bad)


# ── Create: components ────────────────────────────────────────────────────────


def test_create_builds_live_and_estimate_components(stubs):
    user = _user()
    plan = _plan(user)
    created = _create(user, plan["id"])
    comps = _by_id(created.subject["components"])
    assert list(comps) == ["flight", "hotel", "activity-0", "activity-1", "sim"]

    f = comps["flight"]
    assert (f["type"], f["live"], f["price"], f["source"], f["status"]) == (
        "flight",
        True,
        612.0,
        "google_flights",
        "ok",
    )
    assert f["subject"]["origin_code"] and f["subject"]["destination_code"]
    assert f["subject"]["departure_date"] == "2026-12-10"
    assert f["subject"]["num_travelers"] == 2
    # it is Google's cheapest fare for the dates, not the picked flight
    assert f["label"] == "Flights — cheapest fare on your dates"
    assert f["detail"].startswith("Google Flights · Berlin ⇄ Lisbon · 10–14 Dec")
    assert f["detail"].endswith("2 travellers")

    h = comps["hotel"]
    assert (h["live"], h["price"], h["source"]) == (True, 398.0, "google_hotels")
    assert h["subject"] == {
        "name": "Lumen Hotel & The Lisbon Light Show",
        "requested_name": "Lumen Hotel",
        "city": "Lisbon",
        "property_token": "tok-lumen",
        "check_in": "2026-12-10",
        "check_out": "2026-12-14",
        "adults": 2,
        "rooms": 1,
    }
    assert h["unit_price"] == pytest.approx(99.5) and h["unit"] == "per night"
    assert h["detail"] == "Google Hotels · 4 nights · 1 room · $99.50 per night"

    a = comps["activity-1"]
    assert a["live"] is True and a["source"] == "getyourguide_via_google"
    assert a["price"] == pytest.approx(66.92)  # $33.46 per person × 2
    assert (a["unit_price"], a["unit"]) == (33.46, "per person")
    assert a["detail"] == "from $33.46 per person × 2"
    assert set(a["subject"]) >= {
        "name",
        "city",
        "listing_url",
        "listing_title",
        "provider",
        "query",
        "travellers",
    }
    assert a["subject"]["travellers"] == 2

    s = comps["sim"]
    assert (s["type"], s["live"], s["price"], s["source"], s["status"]) == (
        "other",
        False,
        13.0,
        "ai_estimate",
        "estimate",
    )

    total = 612 + 398 + 45.74 + 66.92 + 13
    assert created.baseline.price == pytest.approx(total)
    assert created.baseline.status == "ok"
    assert created.expires_on == "2026-12-10"
    assert created.plan_id == plan["id"]
    assert created.title == "Lisbon escape"
    assert created.subtitle == "Lisbon · 10–14 Dec · 2 travellers"
    assert created.subject["plan_id"] == plan["id"]
    assert created.subject["city"] == "Lisbon"
    assert len(created.baseline.breakdown) == 5
    # one flight + one hotel search + two activity searches
    assert created.baseline.calls == 4


def test_unmatched_parts_become_frozen_estimates(stubs):
    stubs.hotel_offers = [_offer("Some Other Place", 300.0)]
    stubs.listings = {}
    user = _user()
    created = _create(user, _plan(user)["id"])
    comps = _by_id(created.subject["components"])
    assert comps["hotel"]["live"] is False
    assert comps["hotel"]["price"] == 440.0  # the plan's total_price_usd
    assert comps["hotel"]["source"] == "ai_estimate"
    assert comps["hotel"]["status"] == "estimate"
    # activities: AI price per person × travellers, as estimates
    assert comps["activity-0"]["live"] is False
    assert comps["activity-0"]["price"] == 60.0
    assert comps["activity-0"]["detail"] == "$30 per person × 2 (estimate)"
    assert comps["hotel"]["detail"] == "4 nights (estimate)"
    assert created.baseline.price == pytest.approx(612 + 440 + 60 + 60 + 13)


def test_hotel_estimate_from_nightly_when_no_total(stubs):
    stubs.hotel_offers = []
    user = _user()
    sel = {**SELECTIONS, "hotel": {"name": "X", "price_per_night_usd": 100.0}}
    created = _create(user, _plan(user, sel)["id"])
    assert _by_id(created.subject["components"])["hotel"]["price"] == 400.0  # 4 n


def test_category_and_non_usd_activity_matches_are_estimates(stubs):
    stubs.listings = {
        "Jeronimos Monastery": [_listing("Jeronimos Monastery", 12.3, kind="category")],
        "Small Group Walking Tour of Belem": [
            _listing("Small Group Walking Tour of Belém", 30.0, currency="EUR")
        ],
    }
    user = _user()
    created = _create(user, _plan(user)["id"])
    comps = _by_id(created.subject["components"])
    for cid in ("activity-0", "activity-1"):
        assert comps[cid]["live"] is False
        assert comps[cid]["source"] == "ai_estimate"
        assert comps[cid]["price"] == 60.0
        assert comps[cid]["currency"] == "USD"


def test_non_usd_match_without_ai_price_is_listed_but_not_totalled(stubs):
    stubs.listings = {
        "Fado show": [_listing("Fado show", 25.0, currency="EUR", slug="fado")]
    }
    user = _user()
    sel = {"flight": FLIGHT, "activities": [{"name": "Fado show"}]}
    created = _create(user, _plan(user, sel)["id"])
    comp = _by_id(created.subject["components"])["activity-0"]
    assert comp["live"] is False and comp["status"] == "estimate"
    assert (comp["price"], comp["currency"], comp["in_total"]) == (50.0, "EUR", False)
    assert created.baseline.price == 612.0


def test_at_most_five_live_activities_at_create(stubs):
    names = [f"Tour number {i}" for i in range(7)]
    stubs.listings = {
        n: [_listing(n, 10.0 + i, slug=f"t{i}")] for i, n in enumerate(names)
    }
    user = _user()
    sel = {"flight": FLIGHT, "activities": _acts(*names, price=20.0)}
    created = _create(user, _plan(user, sel)["id"])
    comps = [c for c in created.subject["components"] if c["type"] == "activity"]
    assert [c["live"] for c in comps] == [True] * 5 + [False] * 2
    assert stubs.count("activity_find") == 5


def test_create_spends_at_most_ten_calls(stubs, monkeypatch):
    # every activity search may need the Viator query too (2 calls): with
    # flight + hotel that leaves room for 4 activities
    names = [f"Tour number {i}" for i in range(6)]
    stubs.listings = {}  # nothing matches → GetYourGuide then Viator each
    user = _user()
    sel = {"flight": FLIGHT, "hotel": HOTEL, "activities": _acts(*names)}
    created_or_none = _create(user, _plan(user, sel)["id"])
    assert stubs.count("activity_find") == 4
    assert created_or_none.baseline.calls == 1 + 1 + 4 * 2


def test_cached_lookups_are_free(stubs):
    user = _user()
    plan = _plan(user)
    cache = get_cache()
    cache[
        hotel_prices.find_cache_key(
            "Lumen Hotel Lisbon", "2026-12-10", "2026-12-14", 2, 1
        )
    ] = ()
    created = _create(user, plan["id"])
    assert created.baseline.calls == 3


def test_no_live_component_is_no_live_price(stubs):
    stubs.fares = [None]
    stubs.hotel_offers = []
    stubs.listings = {}
    user = _user()
    result = _create(user, _plan(user)["id"])
    assert isinstance(result, NoLivePrice)
    assert result.message == "We can't find a live price for any part of this trip yet"
    assert result.suggestions == []
    assert result.estimate["source"] == "ai_estimate"
    assert result.estimate["price"] == pytest.approx(640 + 440 + 60 + 60 + 13)
    assert result.calls >= 1


def test_estimates_only_plan_is_no_live_price(stubs):
    user = _user()
    result = _create(user, _plan(user, {"sim": {"price_usd": 13.0}})["id"])
    assert isinstance(result, NoLivePrice)
    assert result.calls == 0


def test_flight_estimate_when_the_route_has_no_airport(stubs):
    user = _user()
    search = {**SEARCH, "origin": "Qqqzzx Nowhere"}
    created = _create(user, _plan(user, search=search)["id"])
    f = _by_id(created.subject["components"])["flight"]
    assert (f["live"], f["price"], f["source"]) == (False, 640.0, "ai_estimate")
    assert stubs.count("flight") == 0


def test_multi_city_plans_price_flight_legs_and_hotel_as_estimates(stubs):
    user = _user()
    search = {**SEARCH, "destinations": ["Paris", "Rome"]}
    sel = {"flights": [{"price_usd": 100.0}, {"price_usd": 150.0}], "hotel": HOTEL}
    result = _create(user, _plan(user, sel, search)["id"])
    assert isinstance(result, NoLivePrice)  # nothing live to watch
    assert result.estimate["price"] == 250.0 + 440.0
    assert stubs.calls == []


def test_another_users_plan_and_a_missing_plan_look_the_same(stubs):
    alice, bob = _user(), _user()
    plan = _plan(alice)
    errors = []
    for pid in (plan["id"], 987654):
        with pytest.raises(trip.PlanNotFound) as exc:
            _create(bob, pid)
        errors.append((str(exc.value), exc.value.status_code))
    assert errors[0] == errors[1] == ("Plan not found", 404)
    assert stubs.calls == []


def test_plan_without_departure_date_is_invalid(stubs):
    user = _user()
    plan = _plan(user, search={**SEARCH, "departure_date": None})
    with pytest.raises(InvalidSpec):
        _create(user, plan["id"])


def test_departed_or_departing_today_plan_is_invalid_before_any_call(
    stubs, monkeypatch
):
    monkeypatch.setattr(fare_watch, "utcnow", lambda: NOW.replace(month=12, day=10))
    user = _user()
    plan = _plan(user)
    with pytest.raises(InvalidSpec) as exc:
        _create(user, plan["id"])
    assert "already started" in str(exc.value)
    assert stubs.calls == []


def test_hotel_rooms_fit_the_party(stubs):
    user = _user()
    created = _create(user, _plan(user, search={**SEARCH, "num_travelers": 5})["id"])
    find = next(c for c in stubs.calls if c[0] == "hotel_find")
    assert (find[5], find[6]) == (5, 3)  # 5 adults in 3 rooms
    h = _by_id(created.subject["components"])["hotel"]["subject"]
    assert (h["adults"], h["rooms"]) == (5, 3)


def test_a_plan_without_a_city_skips_hotel_and_activity_lookups(stubs):
    user = _user()
    result = _create(user, _plan(user, search={**SEARCH, "destination": ""})["id"])
    assert stubs.calls == []  # no "hotels in your" searches
    assert isinstance(result, NoLivePrice)


def test_invalid_spec_declares_its_status():
    assert InvalidSpec.status_code == 422
    assert trip.PlanNotFound().status_code == 404


def test_quota_partway_through_create_reports_the_calls_made(stubs):
    stubs.fares = [serp_flights.SerpAPIError("quota", quota_exceeded=True)]
    user = _user()
    with pytest.raises(serp_flights.SerpAPIError) as exc:
        _create(user, _plan(user)["id"])
    # the flight call failed (1) + hotel search (1) + 2 activity searches (2)
    assert exc.value.calls == 4


def test_check_reports_the_calls_it_made(stubs):
    created = _created_with_prices(stubs)
    stubs.fares = [612.0]
    stubs.hotel_prices = [_hp(398.0)]
    u0, u1 = _url(created, "activity-0"), _url(created, "activity-1")
    stubs.activity_prices = {u0: [_ap(u0, 22.87)], u1: [_ap(u1, 33.46)]}
    # activity-1's search is already cached: it costs nothing
    q1 = _by_id(created.subject["components"])["activity-1"]["subject"]["query"]
    get_cache()[activity_prices.search_cache_key(q1)] = {"results": []}
    w = _watch(created)
    assert trip.SOURCE.estimate_calls(w) == 3
    assert run(trip.SOURCE.check(w, "k")).calls == 3


# ── Check ─────────────────────────────────────────────────────────────────────


def _created_with_prices(stubs, user=None, selections=None):
    user = user or _user()
    created = _create(user, _plan(user, selections)["id"])
    stubs.calls.clear()
    get_cache().clear()  # a later check: nothing cached any more
    return created


def _url(created, cid):
    return _by_id(created.subject["components"])[cid]["subject"]["listing_url"]


def test_check_reprices_live_parts_and_holds_estimates(stubs):
    created = _created_with_prices(stubs)
    stubs.fares = [542.0]
    stubs.hotel_prices = [_hp(356.0)]
    stubs.activity_prices = {
        _url(created, "activity-0"): [_ap(_url(created, "activity-0"), 20.0)],
        _url(created, "activity-1"): [_ap(_url(created, "activity-1"), 33.46)],
    }
    w = _watch(created)
    assert trip.SOURCE.estimate_calls(w) == 4
    obs = run(trip.SOURCE.check(w, "k"))
    assert obs.status == "ok"
    assert obs.price == pytest.approx(542 + 356 + 40 + 66.92 + 13)
    assert obs.calls == 4
    b = _by_id(obs.breakdown)
    assert (b["flight"]["previous_price"], b["flight"]["price"]) == (612.0, 542.0)
    assert b["flight"]["delta"] == -70.0
    assert b["hotel"]["delta"] == -42.0
    assert b["sim"]["status"] == "estimate" and b["sim"]["delta"] == 0
    assert {c["group"] for c in obs.breakdown} == {
        "flights",
        "stay",
        "activities",
        "other",
    }


def test_check_counts_cached_answers_as_free(stubs):
    created = _created_with_prices(stubs)
    h = _by_id(created.subject["components"])["hotel"]["subject"]
    key = hotel_prices.price_cache_key(
        h["property_token"], h["check_in"], h["check_out"], h["adults"], h["rooms"]
    )
    get_cache()[key] = _hp(398.0)
    stubs.fares = [612.0]
    stubs.hotel_prices = [_hp(398.0)]
    stubs.activity_prices = {
        u: [_ap(u, 22.87)]
        for u in (_url(created, "activity-0"), _url(created, "activity-1"))
    }
    w = _watch(created)
    assert trip.SOURCE.estimate_calls(w) == 3
    assert run(trip.SOURCE.check(w, "k")).calls == 3


def test_estimate_calls_never_exceeds_eight(stubs):
    names = [f"Tour number {i}" for i in range(8)]
    stubs.listings = {n: [_listing(n, 10.0, slug=f"t{i}")] for i, n in enumerate(names)}
    sel = {"flight": FLIGHT, "hotel": HOTEL, "activities": _acts(*names)}
    created = _created_with_prices(stubs, selections=sel)
    assert trip.SOURCE.estimate_calls(_watch(created)) == 1 + 1 + 5
    assert trip.CHECK_CALL_CAP == 8


def test_activities_rotate_fairly_and_unchecked_ones_go_stale(stubs):
    names = [f"Tour number {i}" for i in range(7)]
    stubs.listings = {n: [_listing(n, 10.0, slug=f"t{i}")] for i, n in enumerate(names)}
    # 7 activities but only 5 live at create: give it room by making them live
    # via a plan whose first 5 match; the rest are estimates
    sel = {"activities": _acts(*names), "flight": FLIGHT}
    created = _created_with_prices(stubs, selections=sel)
    live = [
        c["id"]
        for c in created.subject["components"]
        if c.get("live") and c["type"] == "activity"
    ]
    assert len(live) == 5

    # Make a watch with 7 live activities to exercise rotation
    comps = copy.deepcopy(created.subject["components"])
    for c in comps:
        if c["type"] == "activity" and not c["live"]:
            src = next(x for x in comps if x["id"] == live[0])
            c.update(
                live=True,
                source=src["source"],
                status="ok",
                subject={
                    **src["subject"],
                    "listing_url": f"https://www.getyourguide.com/x/{c['id']}",
                },
            )
    subject = {**created.subject, "components": comps}
    created.subject = subject
    created.baseline.breakdown = [
        dict(c, checked_at="2026-11-04T00:00:00+00:00") for c in comps
    ]
    urls = {
        c["id"]: c["subject"]["listing_url"] for c in comps if c["type"] == "activity"
    }
    stubs.activity_prices = {u: [_ap(u, 9.0), _ap(u, 9.0)] for u in urls.values()}

    w = _watch(created)
    first = run(trip.SOURCE.check(w, "k"))
    b1 = _by_id(first.breakdown)
    checked1 = {cid for cid in urls if b1[cid]["status"] == "ok"}
    stale1 = {cid for cid in urls if b1[cid]["status"] == "stale"}
    assert len(checked1) == 5 and len(stale1) == 2
    for cid in stale1:  # kept their last observed price, still live
        assert b1[cid]["live"] is True
        assert b1[cid]["price"] == _by_id(created.baseline.breakdown)[cid]["price"]

    w2 = _watch(created, last=first)
    second = run(trip.SOURCE.check(w2, "k"))
    b2 = _by_id(second.breakdown)
    checked2 = {cid for cid in urls if b2[cid]["status"] == "ok"}
    assert stale1 <= checked2  # the ones skipped last time go first
    assert len(checked2) == 5


def test_unavailable_part_keeps_its_last_price_and_is_flagged(stubs):
    created = _created_with_prices(stubs)
    stubs.fares = [600.0]
    stubs.hotel_prices = [_hp(0, available=False)]
    stubs.activity_prices = {
        u: [_ap(u, 0, available=False)]
        for u in (_url(created, "activity-0"), _url(created, "activity-1"))
    }
    obs = run(trip.SOURCE.check(_watch(created), "k"))
    assert obs.status == "ok"
    b = _by_id(obs.breakdown)
    assert b["hotel"]["status"] == "unavailable" and b["hotel"]["price"] == 398.0
    assert b["activity-0"]["status"] == "unavailable"
    assert obs.price == pytest.approx(600 + 398 + 45.74 + 66.92 + 13)


def test_flight_and_hotel_unavailable_but_activities_priced_is_ok(stubs):
    created = _created_with_prices(stubs)
    stubs.fares = [None]
    stubs.hotel_prices = [_hp(0, available=False)]
    stubs.activity_prices = {
        u: [_ap(u, 20.0)]
        for u in (_url(created, "activity-0"), _url(created, "activity-1"))
    }
    obs = run(trip.SOURCE.check(_watch(created), "k"))
    assert obs.status == "ok"
    b = _by_id(obs.breakdown)
    assert (b["flight"]["status"], b["flight"]["price"]) == ("unavailable", 612.0)
    assert (b["hotel"]["status"], b["hotel"]["price"]) == ("unavailable", 398.0)
    assert obs.price == pytest.approx(612 + 398 + 40 + 40 + 13)


def test_only_flight_live_and_unavailable_with_activities_priced_is_ok(stubs):
    stubs.hotel_offers = []  # hotel stays an estimate
    created = _created_with_prices(stubs)
    stubs.fares = [None]
    stubs.activity_prices = {
        u: [_ap(u, 20.0)]
        for u in (_url(created, "activity-0"), _url(created, "activity-1"))
    }
    obs = run(trip.SOURCE.check(_watch(created), "k"))
    assert obs.status == "ok"


def test_no_live_part_priced_is_an_unavailable_look(stubs):
    created = _created_with_prices(stubs)
    stubs.fares = [None]
    stubs.hotel_prices = [_hp(0, available=False)]
    stubs.activity_prices = {
        u: [_ap(u, 0, available=False)]
        for u in (_url(created, "activity-0"), _url(created, "activity-1"))
    }
    obs = run(trip.SOURCE.check(_watch(created), "k"))
    assert obs.status == "unavailable" and obs.price is None
    assert obs.breakdown  # the UI still shows what happened


def test_a_part_that_errors_keeps_its_price_but_all_errors_raise(stubs):
    created = _created_with_prices(stubs)
    stubs.fares = [serp_flights.SerpAPIError("SerpAPI HTTP 500")]
    stubs.hotel_prices = [_hp(380.0)]
    stubs.activity_prices = {
        u: [_ap(u, 22.87), _ap(u, 22.87)]
        for u in (_url(created, "activity-0"), _url(created, "activity-1"))
    }
    obs = run(trip.SOURCE.check(_watch(created), "k"))
    b = _by_id(obs.breakdown)
    assert b["flight"]["status"] == "error" and b["flight"]["price"] == 612.0

    stubs.fares = [serp_flights.SerpAPIError("SerpAPI HTTP 500")]
    stubs.hotel_prices = [serp_flights.SerpAPIError("SerpAPI HTTP 500")]
    stubs.activity_prices = {
        u: [serp_flights.SerpAPIError("SerpAPI HTTP 500")]
        for u in (_url(created, "activity-0"), _url(created, "activity-1"))
    }
    with pytest.raises(serp_flights.SerpAPIError):
        run(trip.SOURCE.check(_watch(created), "k"))


def test_quota_exceeded_anywhere_postpones(stubs):
    created = _created_with_prices(stubs)
    stubs.fares = [serp_flights.SerpAPIError("quota", quota_exceeded=True)]
    stubs.hotel_prices = [_hp(380.0)]
    stubs.activity_prices = {
        u: [_ap(u, 22.87)]
        for u in (_url(created, "activity-0"), _url(created, "activity-1"))
    }
    with pytest.raises(serp_flights.SerpAPIError) as exc:
        run(trip.SOURCE.check(_watch(created), "k"))
    assert exc.value.quota_exceeded


def test_activity_in_another_currency_on_check_is_unavailable(stubs):
    created = _created_with_prices(stubs)
    u0, u1 = _url(created, "activity-0"), _url(created, "activity-1")
    stubs.fares = [612.0]
    stubs.hotel_prices = [_hp(398.0)]
    stubs.activity_prices = {u0: [_ap(u0, 20.0, currency="EUR")], u1: [_ap(u1, 33.46)]}
    obs = run(trip.SOURCE.check(_watch(created), "k"))
    b = _by_id(obs.breakdown)
    assert b["activity-0"]["status"] == "unavailable"
    assert b["activity-0"]["price"] == pytest.approx(45.74)


# ── Notification copy ─────────────────────────────────────────────────────────


def _obs_from(created, **prices):
    """An ok observation with some component prices changed."""
    rows = []
    for c in created.baseline.breakdown:
        c = dict(c)
        if c["id"] in prices:
            c["price"] = prices[c["id"]]
        rows.append(c)
    total = sum(c["price"] for c in rows if c.get("in_total", True))
    return PriceObservation(price=total, breakdown=rows, source="trip")


def test_drop_copy_explains_by_component(stubs):
    created = _created_with_prices(stubs)
    w = _watch(created)
    obs = _obs_from(created, flight=542.0, hotel=356.0)
    note = trip.SOURCE.compose("trip_drop", w, obs, created.baseline.price)
    assert (
        note["title"] == "🧳 Your Lisbon trip is $112 cheaper: flights −$70, hotel −$42"
    )
    assert "Estimates (SIM / eSIM) are held fixed" in note["body"]
    assert "cheapest Google Flights fare on your dates" in note["body"]
    assert note["data"]["components"] == [
        {"group": "flights", "label": "flights", "delta": -70.0},
        {"group": "stay", "label": "hotel", "delta": -42.0},
    ]


def test_copy_lists_only_parts_that_moved_and_groups_activities(stubs):
    created = _created_with_prices(stubs)
    obs = _obs_from(
        created, **{"activity-0": 15.74, "activity-1": 36.92, "flight": 590.0}
    )
    note = trip.SOURCE.compose(
        "trip_drop", _watch(created), obs, created.baseline.price
    )
    assert (
        note["title"]
        == "🧳 Your Lisbon trip is $82 cheaper: activities −$60, flights −$22"
    )


def test_copy_measures_from_the_stored_last_alert_look(stubs):
    created = _created_with_prices(stubs)
    mid = _obs_from(created, flight=560.0)  # the last alert, at this total
    w = {
        **_watch(created),
        "last_notified_price": mid.price,
        "own_peak_price": mid.price,
        "reference_looks": {
            "baseline": created.baseline.breakdown,
            "last_alert": mid.breakdown,
            "peak": mid.breakdown,
        },
    }
    obs = _obs_from(created, flight=560.0, hotel=320.0)
    note = trip.SOURCE.compose("trip_drop", w, obs, mid.price)
    assert note["title"] == "🧳 Your Lisbon trip is $78 cheaper: hotel −$78"


def test_copy_measures_from_the_stored_peak_once_rearmed(stubs):
    created = _created_with_prices(stubs)
    alert = _obs_from(created, flight=500.0)  # alerted at base − 112
    peak = _obs_from(created, flight=700.0)  # rebounded ≥ a step above it
    w = {
        **_watch(created),
        "last_notified_price": alert.price,
        "own_peak_price": peak.price,
        "reference_looks": {
            "baseline": created.baseline.breakdown,
            "last_alert": alert.breakdown,
            "peak": peak.breakdown,
        },
    }
    obs = _obs_from(created, flight=640.0, hotel=350.0)
    note = trip.SOURCE.compose("trip_drop", w, obs, peak.price)
    assert (
        note["title"] == "🧳 Your Lisbon trip is $108 cheaper: flights −$60, hotel −$48"
    )


def test_without_a_stored_reference_look_only_the_total_is_explained(stubs):
    created = _created_with_prices(stubs)
    obs = _obs_from(created, flight=542.0, hotel=356.0)
    gone = {**_watch(created), "reference_looks": None}
    note = trip.SOURCE.compose("trip_drop", gone, obs, created.baseline.price)
    assert note["title"] == "🧳 Your Lisbon trip is $112 cheaper"
    assert note["data"]["components"] == []
    # a stored look that doesn't add up to the reference is not trusted either
    other = _obs_from(created, flight=100.0)
    w = {**_watch(created), "reference_looks": {"baseline": other.breakdown}}
    note = trip.SOURCE.compose("trip_drop", w, obs, created.baseline.price)
    assert note["title"] == "🧳 Your Lisbon trip is $112 cheaper"


def test_target_copy(stubs):
    created = _created_with_prices(stubs)
    w = {**_watch(created), "target_price": 1100.0}
    obs = _obs_from(created, flight=500.0)
    note = trip.SOURCE.compose("trip_target", w, obs, created.baseline.price)
    assert note["title"] == (
        f"🧳 Your Lisbon trip is now ${round(obs.price):,} — below your $1,100 target"
    )
    assert "Flights −$112" in note["body"]


def test_copy_names_at_most_two_estimates(stubs):
    names = [f"Tour number {i}" for i in range(6)]
    stubs.listings = {}
    sel = {**SELECTIONS, "activities": _acts(*names)}
    created = _created_with_prices(stubs, selections=sel)
    obs = _obs_from(created, flight=500.0)
    note = trip.SOURCE.compose(
        "trip_drop", _watch(created), obs, created.baseline.price
    )
    assert (
        "Estimates (Tour number 0, Tour number 1 +5 more) are held fixed"
        in note["body"]
    )


def test_copy_says_which_parts_had_no_live_price(stubs):
    created = _created_with_prices(stubs)
    obs = _obs_from(created, flight=500.0)
    for r in obs.breakdown:
        if r["id"] == "hotel":
            r["status"] = "unavailable"
    note = trip.SOURCE.compose(
        "trip_drop", _watch(created), obs, created.baseline.price
    )
    assert (
        "Lumen Hotel & The Lisbon Light Show: no live price on this check "
        "(last seen $398)." in note["body"]
    )


def test_copy_without_a_city(stubs):
    created = _created_with_prices(stubs)
    created.subject["city"] = None
    obs = _obs_from(created, flight=500.0)
    note = trip.SOURCE.compose(
        "trip_drop", _watch(created), obs, created.baseline.price
    )
    assert note["title"].startswith("🧳 Your trip is $112 cheaper")


# ── Pipeline: estimates never alert alone, threshold ──────────────────────────


@pytest.fixture
def piped(stubs, monkeypatch):
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 500)
    monkeypatch.setattr(settings, "smtp_host", "")
    with get_connection() as conn:
        conn.execute("DELETE FROM fare_watch_quota")
        conn.execute("DELETE FROM fare_watch_user_quota")
    return stubs


def _stored(user, created, mode="any_drop", target=None):
    return price_watch.record_created(
        user["id"],
        "trip",
        created,
        match_key=trip.SOURCE.match_key({"plan_id": created.plan_id}),
        alert_mode=mode,
        target_price=target,
        email_enabled=False,
        now=NOW,
    )


def _queue(stubs, created, flight, hotel=398.0, acts=(22.87, 33.46)):
    stubs.fares = [flight]
    stubs.hotel_prices = [_hp(hotel)]
    stubs.activity_prices = {
        _url(created, f"activity-{i}"): [_ap(_url(created, f"activity-{i}"), p)]
        for i, p in enumerate(acts)
    }


def _check(watch_id, when):
    return run(price_watch.check_watch(watch_id, now=when, api_key="k", manual=True))


def test_threshold_on_the_total_is_max_25_or_4_percent(piped):
    user = _user()
    created = _create(user, _plan(user)["id"])
    w = _stored(user, created)
    base = created.baseline.price  # ≈ 1135.66 → step = max(25, 45.4) = 45.4
    _queue(piped, created, 612.0 - 40)  # −$40 total: under the step
    out = _check(w["id"], NOW + timedelta(hours=12))
    assert out.status == "checked" and out.notification is None
    _queue(piped, created, 612.0 - 50)  # −$50 total ≥ 4 %
    out = _check(w["id"], NOW + timedelta(hours=24))
    assert out.notification is not None
    assert out.notification["kind"] == "trip_drop"
    assert out.notification["title"].startswith(
        "🧳 Your Lisbon trip is $50 cheaper: flights −$50"
    )
    assert out.notification["data"]["watch_kind"] == "trip"
    assert out.watch["last_price"] == pytest.approx(base - 50)


def test_estimates_never_alert_on_their_own(piped):
    user = _user()
    plan = _plan(user)
    created = _create(user, plan["id"])
    w = _stored(user, created)
    # The plan's estimates get much cheaper afterwards (hotel, SIM, activities
    # all near zero); the watch's estimates stay frozen, nothing live moves.
    cheaper = copy.deepcopy(SELECTIONS)
    cheaper["hotel"]["total_price_usd"] = 1.0
    cheaper["sim"]["price_usd"] = 1.0
    for a in cheaper["activities"]:
        a["price_usd"] = 1.0
    from app.db.plans_db import update_plan

    update_plan(plan["id"], user["username"], None, cheaper)
    stubs = piped
    stubs.hotel_offers = []  # (not consulted by checks)
    _queue(stubs, created, 612.0)
    out = _check(w["id"], NOW + timedelta(hours=12))
    assert out.notification is None
    assert out.watch["last_price"] == pytest.approx(created.baseline.price)
    sim = _by_id(out.watch["last_observation"]["breakdown"])["sim"]
    assert (sim["price"], sim["status"]) == (13.0, "estimate")


def test_reference_looks_are_stored_for_the_baseline_alerts_and_peaks(piped):
    user = _user()
    created = _create(user, _plan(user)["id"])
    w = _stored(user, created)
    row = price_watch_db.get_watch(w["id"])
    assert row["reference_looks"] == {"baseline": created.baseline.breakdown}

    _queue(piped, created, 500.0)  # an alert: −$112
    out = _check(w["id"], NOW + timedelta(hours=12))
    assert out.notification is not None
    looks = price_watch_db.get_watch(w["id"])["reference_looks"]
    alert_flight = _by_id(looks["last_alert"])["flight"]["price"]
    assert alert_flight == 500.0 and looks["peak"] == looks["last_alert"]
    assert looks["baseline"] == created.baseline.breakdown

    _queue(piped, created, 520.0)  # a rebound: a new peak, no alert
    out = _check(w["id"], NOW + timedelta(hours=36))
    assert out.notification is None
    looks = price_watch_db.get_watch(w["id"])["reference_looks"]
    assert _by_id(looks["peak"])["flight"]["price"] == 520.0
    assert _by_id(looks["last_alert"])["flight"]["price"] == 500.0

    _queue(piped, created, 510.0)  # lower than the peak: the peak look stays
    _check(w["id"], NOW + timedelta(hours=60))
    looks = price_watch_db.get_watch(w["id"])["reference_looks"]
    assert _by_id(looks["peak"])["flight"]["price"] == 520.0

    # the API never shows them
    from app.api.routes.price_watches import serialize

    assert "reference_looks" not in serialize(price_watch_db.get_watch(w["id"]))


def test_alert_explained_after_history_is_pruned(piped, monkeypatch):
    monkeypatch.setattr(price_watch_db, "HISTORY_KEEP", 1)
    user = _user()
    created = _create(user, _plan(user)["id"])
    w = _stored(user, created)
    _queue(piped, created, 500.0)  # alert vs baseline (flights −$112)
    _check(w["id"], NOW + timedelta(hours=12))
    _queue(piped, created, 505.0)  # a quiet look pushes the alert row out
    assert _check(w["id"], NOW + timedelta(hours=24)).notification is None
    _queue(piped, created, 500.0, hotel=300.0)  # −$98 since that alert
    out = _check(w["id"], NOW + timedelta(hours=48))
    assert out.notification["title"] == "🧳 Your Lisbon trip is $98 cheaper: hotel −$98"


def test_plan_deleted_watch_keeps_checking_its_frozen_subject(piped):
    user = _user()
    plan = _plan(user)
    created = _create(user, plan["id"])
    w = _stored(user, created)
    delete_plan(plan["id"], user["username"])
    _queue(piped, created, 500.0)
    out = _check(w["id"], NOW + timedelta(hours=12))
    assert out.status == "checked" and out.notification is not None


def test_unavailable_look_goes_through_the_pipeline(piped):
    user = _user()
    created = _create(user, _plan(user)["id"])
    w = _stored(user, created)
    piped.fares = [None]
    piped.hotel_prices = [_hp(0, available=False)]
    piped.activity_prices = {
        _url(created, f"activity-{i}"): [
            _ap(_url(created, f"activity-{i}"), 0, available=False)
        ]
        for i in range(2)
    }
    out = _check(w["id"], NOW + timedelta(hours=12))
    assert out.status == "unavailable"
    hist = price_watch_db.get_history(w["id"])
    assert hist[-1]["price"] is None and hist[-1]["breakdown"]


# ── API (real source, SerpAPI HTTP faked from fixtures) ───────────────────────


def _fixture(path):
    return json.loads((FIXTURES / path).read_text())


FLIGHTS_BODY = {
    "best_flights": [{"price": 612}, {"price": 700}],
    "other_flights": [{"price": 655}],
    "price_insights": {"lowest_price": 612, "price_level": "typical"},
}


class FakeSerp:
    """Stands in for the shared SerpAPI httpx client."""

    def __init__(self):
        self.params: list[dict] = []
        self.flight_price = 612
        self.google_body = None  # engine=google answer (default: GYG fixture)
        self.quota_on = None  # engine answering 429

    async def get(self, url, params=None):
        params = dict(params or {})
        assert params.pop("api_key", None) == "test-key"
        self.params.append(params)
        engine = params.get("engine")
        if engine == self.quota_on:
            return httpx.Response(429, json={}, request=httpx.Request("GET", url))
        if engine == "google_flights":
            body = copy.deepcopy(FLIGHTS_BODY)
            body["best_flights"][0]["price"] = self.flight_price
        elif engine == "google_hotels" and params.get("property_token"):
            body = _fixture("hotels/property_details_lumen_generic_q.json")
        elif engine == "google_hotels":
            body = _fixture("hotels/named_search_lumen_single_property.json")
        elif self.google_body is not None:
            body = copy.deepcopy(self.google_body)
        elif "viator" in params.get("q", ""):
            body = _fixture("activities/viator_belem_tower.json")
        else:
            body = _fixture("activities/gyg_belem_tower.json")
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))


@pytest.fixture
def serp(monkeypatch, client):
    fake = FakeSerp()
    for mod in (serp_flights, hotel_prices, activity_prices):
        for name in ("_get_client", "get_serp_client"):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, lambda: fake)
    monkeypatch.setattr(settings, "serpapi_key", "test-key")
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 200)
    monkeypatch.setattr(settings, "fare_watch_max_active_per_user", 10)
    monkeypatch.setattr(fare_watch, "utcnow", lambda: NOW)
    with get_connection() as conn:
        conn.execute("DELETE FROM fare_watch_quota")
        conn.execute("DELETE FROM fare_watch_user_quota")
    return fake


def _login(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': user['username']})}"}


def _post(client, user, plan_id, **extra):
    return client.post(
        "/api/price-watches",
        json={"kind": "trip", "trip": {"plan_id": plan_id}, **extra},
        headers=_login(user),
    )


def _calls_used():
    with get_connection() as conn:
        row = conn.execute("SELECT SUM(calls) AS n FROM fare_watch_quota").fetchone()
    return row["n"] or 0


def test_api_create_reports_live_and_estimate_components(client, serp):
    user = _user()
    plan = _plan(user)
    r = _post(client, user, plan["id"])
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["kind"] == "trip" and w["already_watching"] is False
    assert w["plan_id"] == plan["id"] and w["expires_on"] == "2026-12-10"
    comps = _by_id(w["subject"]["components"])
    assert comps["flight"]["live"] and comps["flight"]["price"] == 612
    assert comps["hotel"]["live"] and comps["hotel"]["price"] == 398
    assert comps["hotel"]["subject"]["property_token"]
    assert comps["activity-0"]["live"]  # Jerónimos listing, $22.87 pp
    assert comps["activity-0"]["price"] == pytest.approx(45.74)
    assert comps["activity-1"]["live"]  # Small Group Walking Tour of Belém
    assert comps["sim"]["live"] is False
    assert w["baseline_price"] == pytest.approx(612 + 398 + 45.74 + 66.92 + 13)
    assert w["history"][0]["breakdown"]
    # 1 flight + 1 hotel + 2 GetYourGuide searches (no Viator needed)
    assert len(serp.params) == 4
    assert _calls_used() == 4


def test_api_create_is_404_for_another_users_or_a_missing_plan(client, serp):
    alice, bob = _user(), _user()
    plan = _plan(alice)
    r1 = _post(client, bob, plan["id"])
    r2 = _post(client, bob, 99999999)
    assert r1.status_code == r2.status_code == 404
    assert r1.json() == r2.json() == {"detail": "Plan not found"}
    assert serp.params == []
    assert _calls_used() == 0


def test_api_create_422_when_nothing_is_live(client, serp):
    user = _user()
    plan = _plan(user, {"sim": {"price_usd": 13.0}, "hotel": None})
    r = _post(client, user, plan["id"])
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "no_live_price"
    assert body["message"] == "We can't find a live price for any part of this trip yet"
    assert body["estimate"] == {"price": 13.0, "source": "ai_estimate"}
    assert _calls_used() == 0


def test_api_already_watching_the_plan(client, serp):
    user = _user()
    plan = _plan(user)
    first = _post(client, user, plan["id"]).json()
    n = len(serp.params)
    again = _post(client, user, plan["id"]).json()
    assert again["already_watching"] is True and again["id"] == first["id"]
    assert len(serp.params) == n
    m = client.post(
        "/api/price-watches/match",
        json={"kind": "trip", "trip": {"plan_id": plan["id"]}},
        headers=_login(user),
    ).json()
    assert m["watch"]["id"] == first["id"]


def test_api_check_now_reprices_and_explains_the_drop(client, serp):
    user = _user()
    plan = _plan(user)
    w = _post(client, user, plan["id"]).json()
    get_cache().clear()  # a later check: nothing cached
    serp.flight_price = 542
    serp.params.clear()
    r = client.post(f"/api/price-watches/{w['id']}/check", headers=_login(user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["check_status"] == "checked"
    # Google Hotels' property page now shows $368 for the stay (was $398)
    assert body["last_price"] == pytest.approx(w["baseline_price"] - 100)
    assert body["notification"]["title"] == (
        "🧳 Your Lisbon trip is $100 cheaper: flights −$70, hotel −$30"
    )
    # flight + hotel by token + 2 activity re-searches
    assert len(serp.params) == 4
    b = _by_id(body["last_observation"]["breakdown"])
    assert b["flight"]["delta"] == -70
    notes = notifications_db.list_notifications(user["id"])["items"]
    assert notes[0]["kind"] == "trip_drop"


def test_api_check_now_of_another_users_watch_is_404(client, serp):
    alice, bob = _user(), _user()
    w = _post(client, alice, _plan(alice)["id"]).json()
    r = client.post(f"/api/price-watches/{w['id']}/check", headers=_login(bob))
    assert r.status_code == 404


VIATOR_ITEM = {
    "position": 1,
    "title": "Small Group Walking Tour of Belém",
    "link": "https://www.viator.com/tours/Lisbon/Small-Group-Walking-Tour-of-Belem/d538-12345P1",
    "snippet": "Explore Belém on a 3 hour walking tour.",
    "rich_snippet": {
        "top": {
            "detected_extensions": {
                "rating": 4.8,
                "reviews": 50,
                "price": 31.0,
                "currency": "$",
            },
            "extensions": ["4.8(50)", "From $31.00"],
        }
    },
}


def test_api_counts_real_calls_when_the_gyg_query_finds_a_viator_page(client, serp):
    serp.google_body = {"organic_results": [VIATOR_ITEM]}
    user = _user()
    sel = {"flight": FLIGHT, "activities": _acts("Small Group Walking Tour of Belem")}
    r = _post(client, user, _plan(user, sel)["id"])
    assert r.status_code == 200, r.text
    act = _by_id(r.json()["subject"]["components"])["activity-0"]
    assert act["live"] and act["source"] == "viator_via_google"
    assert not any("viator" in p.get("q", "") for p in serp.params)  # no 2nd query
    assert _calls_used() == len(serp.params) == 2  # flight + one Google search


def test_api_quota_partway_settles_to_the_calls_made(client, serp):
    serp.quota_on = "google_hotels"
    user = _user()
    r = _post(client, user, _plan(user)["id"])
    assert r.status_code == 429
    made = len(serp.params)
    assert made >= 1
    assert _calls_used() == made


def test_sources_without_a_breakdown_store_no_reference_looks(client, monkeypatch):
    from .price_watch_fakes import FakeSource, ok

    monkeypatch.setattr(settings, "fare_watch_daily_call_budget", 500)
    src = FakeSource()
    price_watch.register_source(src)
    try:
        user = _user()
        created = run(src.create({"name": "Lumen"}, user, "k"))
        w = price_watch.record_created(
            user["id"],
            "test",
            created,
            match_key="lumen",
            alert_mode="any_drop",
            target_price=None,
            email_enabled=False,
            now=NOW,
        )
        assert price_watch_db.get_watch(w["id"])["reference_looks"] is None
        src.queue = [ok(300.0)]
        out = _check(w["id"], NOW + timedelta(hours=12))
        assert out.notification is not None
        assert price_watch_db.get_watch(w["id"])["reference_looks"] is None
    finally:
        price_watch.unregister_source("test")


# ── Money wording matches the UI's formatPrice (polish) ──────────────────────


@pytest.mark.parametrize(
    "amount,currency,text",
    [(24.0, "EUR", "€24"), (22.87, "USD", "$22.87"), (30.0, "USD", "$30")],
)
def test_detail_money_matches_ui_rule(amount, currency, text):
    assert trip._money(amount, currency) == text


@pytest.mark.parametrize(
    "delta,text", [(-70.0, "−$70"), (-1.73, "−$1.73"), (42.5, "+$42.50")]
)
def test_signed_moves_keep_small_cents(delta, text):
    assert trip._signed(delta) == text
