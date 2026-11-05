"""Price watches name the city, not the airport code the search form stored.

The Results page sends the destination as an airport code ("LIS"). The
hotel and activity sources and the trip component builder turn a code into
its city ("Lisbon") from the local airport data — never the web — so
subjects, alert copy and Google queries read "Lisbon". Real city names pass
through unchanged.
"""

import asyncio
import copy
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.core.cache import get_cache
from app.db import database
from app.db.database import airport_city
from app.db.plans_db import save_plan
from app.db.users_db import create_user
from app.services import activity_prices, fare_watch, hotel_prices
from app.services.activity_prices import ActivityListing, ActivityPrice
from app.services.fare_watch import FareCheck
from app.services.hotel_prices import HotelOffer, HotelPrice
from app.services.price_sources import activity, hotel, trip

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(fare_watch, "utcnow", lambda: NOW)
    # A code we don't know must never be looked up on the web
    monkeypatch.setattr(
        database, "_web_search_iata", AsyncMock(side_effect=AssertionError("web"))
    )
    get_cache().clear()
    yield
    get_cache().clear()


# ── The lookup ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, city",
    [
        ("LIS", "Lisbon"),
        (" LIS ", "Lisbon"),
        ("JFK", "New York"),
        ("Lisbon", "Lisbon"),
        ("Lisbon, Portugal", "Lisbon, Portugal"),
        ("Rome", "Rome"),
        ("Goa", "Goa"),  # a place, not a code
        ("USA", "USA"),  # a country alias, never a code
        ("QQQ", "QQQ"),  # unknown code: unchanged, no web search
        ("", ""),
    ],
)
def test_airport_city(text, city):
    assert airport_city(text) == city


# ── Hotel source ──────────────────────────────────────────────────────────────


def _hotel_spec(city):
    return {
        "name": "Lumen Hotel",
        "city": city,
        "check_in": "2026-12-10",
        "check_out": "2026-12-14",
        "adults": 2,
    }


def test_hotel_spec_with_a_code_is_the_city():
    src = hotel.SOURCE
    assert src.match_key(_hotel_spec("LIS")) == src.match_key(_hotel_spec("Lisbon"))
    assert "|lisbon|" in src.match_key(_hotel_spec("LIS"))


async def test_hotel_create_queries_and_stores_the_city_name():
    offer = HotelOffer(
        name="Lumen Hotel",
        property_token="tok",
        rate_per_night=92.0,
        total_rate=368.0,
        currency="USD",
        hotel_class=4,
        overall_rating=4.5,
        reviews=100,
        link=None,
        gps=None,
        check_in="2026-12-10",
        check_out="2026-12-14",
        adults=2,
    )
    price = HotelPrice(total=368.0, nightly=92.0, available=True, link=None)
    with (
        patch.object(
            hotel_prices, "find_properties", AsyncMock(return_value=[offer])
        ) as find,
        patch.object(
            hotel_prices, "match_property", lambda name, offers, city: offers[0]
        ),
        patch.object(hotel_prices, "price_property", AsyncMock(return_value=price)),
    ):
        created = await hotel.SOURCE.create(_hotel_spec("LIS"), {"id": "u"}, "k")
    assert find.await_args.args[:2] == ("Lumen Hotel", "Lisbon")
    assert created.subject["city"] == "Lisbon"


# ── Activity source ───────────────────────────────────────────────────────────


def test_activity_spec_with_a_code_is_the_city():
    a = activity.parse_spec({"name": "Belem walking tour", "city": "LIS"})
    assert a["city"] == "Lisbon"
    src = activity.SOURCE
    assert src.match_key({"name": "Belem walking tour", "city": "LIS"}) == (
        src.match_key({"name": "Belem walking tour", "city": "Lisbon"})
    )


async def test_activity_create_queries_google_with_the_city_name():
    calls = []

    async def find(name, city, api_key):
        calls.append(city)
        return []

    with patch.object(activity_prices, "find_listings", find):
        await activity.SOURCE.create(
            {"name": "Belem walking tour", "city": "LIS"}, {"id": "u"}, "k"
        )
    assert calls == ["Lisbon"]
    q = activity_prices.build_query("Belem walking tour", "Lisbon", "getyourguide")
    assert "LIS " not in q and "Lisbon" in q


# ── Trip component builder ────────────────────────────────────────────────────


class _Calls:
    def __init__(self):
        self.hotel: list = []
        self.activity: list = []


@pytest.fixture
def adapters(monkeypatch, client):
    seen = _Calls()

    async def fetch_fares(fw, api_key):
        return FareCheck(price=600.0, calls=1)

    async def find_properties(name, city, ci, co, adults, api_key, rooms=1):
        seen.hotel.append(city)
        return []

    async def find_listings(name, city, api_key):
        seen.activity.append((name, city))
        return [
            ActivityListing(
                provider="getyourguide",
                url=f"https://www.getyourguide.com/x-t{len(seen.activity)}/",
                title=name,
                price_from=20.0,
                currency="USD",
                is_usd=True,
                rating=None,
                reviews=None,
                snippet="",
                page_kind="activity",
                query="q",
            )
        ]

    async def price_listing(listing, query, api_key):
        return ActivityPrice(
            price_from=20.0,
            currency="USD",
            is_usd=True,
            available=True,
            url=listing.url,
            observed="2026-11-04T12:00:00Z",
            source="getyourguide_via_google",
            title=listing.title,
        )

    monkeypatch.setattr(fare_watch, "fetch_fares", fetch_fares)
    monkeypatch.setattr(hotel_prices, "find_properties", find_properties)
    monkeypatch.setattr(activity_prices, "find_listings", find_listings)
    monkeypatch.setattr(activity_prices, "price_listing", price_listing)
    monkeypatch.setattr(
        activity_prices, "match_listing", lambda name, found, city: found[0]
    )
    return seen


def _plan(search, selections):
    user = create_user(f"cn-{uuid.uuid4().hex[:8]}", "pw-123456789")
    plan = save_plan(user["username"], "Trip", search, copy.deepcopy(selections))
    return user, plan


SEARCH = {
    "origin": "BER",
    "destination": "LIS",
    "departure_date": "2026-12-10",
    "return_date": "2026-12-14",
    "num_travelers": 2,
}


def test_trip_with_a_code_destination_uses_the_city_name(adapters):
    sel = {
        "hotel": {"name": "Lumen Hotel", "total_price_usd": 440.0},
        "activities": [{"name": "Belem walking tour", "price_usd": 30.0}],
    }
    user, plan = _plan(SEARCH, sel)
    created = asyncio.run(trip.SOURCE.create({"plan_id": plan["id"]}, user, "k"))
    assert adapters.hotel == ["Lisbon"]
    assert adapters.activity == [("Belem walking tour", "Lisbon")]
    assert created.subject["city"] == "Lisbon"
    assert created.title == "Trip"
    assert "LIS" not in created.subtitle


def test_trip_with_a_city_name_is_unchanged(adapters):
    user, plan = _plan(
        {**SEARCH, "destination": "Lisbon, Portugal"},
        {"activities": [{"name": "Belem walking tour", "price_usd": 30.0}]},
    )
    asyncio.run(trip.SOURCE.create({"plan_id": plan["id"]}, user, "k"))
    assert adapters.activity == [("Belem walking tour", "Lisbon")]


def test_multi_city_activities_use_their_own_leg_city(adapters):
    search = {**SEARCH, "destination": "FCO", "destinations": ["CDG", "FCO"]}
    sel = {
        "activities": [
            {"name": "Louvre tour", "price_usd": 30.0, "city": "CDG"},
            {"name": "Colosseum tour", "price_usd": 30.0, "city": "Rome"},
            {"name": "Mystery tour", "price_usd": 30.0},  # no leg: never guessed
        ]
    }
    user, plan = _plan(search, sel)
    asyncio.run(trip.SOURCE.create({"plan_id": plan["id"]}, user, "k"))
    assert adapters.activity == [("Louvre tour", "Paris"), ("Colosseum tour", "Rome")]
