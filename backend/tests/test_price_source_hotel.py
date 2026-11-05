"""Hotel price source (``price_sources.hotel``): spec validation, matching a
traveller's hotel to a live Google Hotels property, checks and alert copy.

SerpAPI answers come from the recorded fixtures under
tests/fixtures/serpapi/hotels/ (``hotel_prices._call`` is stubbed): no
network.
"""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services import fare_watch, hotel_prices, price_watch, serp_flights
from app.services.price_sources import hotel
from app.services.price_sources.hotel import SOURCE
from app.services.price_watch import (
    CreatedWatch,
    InvalidSpec,
    NoLivePrice,
    PriceObservation,
    PriceSource,
)

FIXTURES = Path(__file__).parent / "fixtures" / "serpapi" / "hotels"
LUMEN_TOKEN = "ChoIkamS5OLO9d2QARoNL2cvMTFrODM4N24zORAB"
BROWNS_TOKEN = "ChkIhLCQwvjO2IYWGg0vZy8xMXE0bTZieDkyEAE"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
USER = {"id": "u-1"}
NO_LIVE = "We couldn't find live prices for this hotel on Google Hotels."


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    from app.core.cache import get_cache

    monkeypatch.setattr(fare_watch, "utcnow", lambda: NOW)
    get_cache().clear()
    yield
    get_cache().clear()


def serp(*responses):
    """Stub the SerpAPI call with ``responses`` in order (deep copies)."""
    return patch.object(
        hotel_prices,
        "_call",
        AsyncMock(side_effect=[copy.deepcopy(r) for r in responses]),
    )


def spec(**over):
    s = {
        "name": "Lumen Hotel",
        "city": "Lisbon",
        "check_in": "2026-12-10",
        "check_out": "2026-12-14",
        "adults": 2,
    }
    s.update(over)
    return s


def watch_for(subject, **over):
    w = {
        "id": 7,
        "kind": "hotel",
        "title": subject.get("name", "Lumen Hotel & The Lisbon Light Show"),
        "subtitle": "10–14 Dec · 2 adults",
        "subject": subject,
        "baseline_price": 398.0,
        "target_price": None,
        "lowest_price": 398.0,
    }
    w.update(over)
    return w


LUMEN_SUBJECT = {
    "name": "Lumen Hotel & The Lisbon Light Show",
    "requested_name": "Lumen Hotel",
    "city": "Lisbon",
    "property_token": LUMEN_TOKEN,
    "check_in": "2026-12-10",
    "check_out": "2026-12-14",
    "adults": 2,
    "rooms": 1,
}


# ── Shape and registration ────────────────────────────────────────────────────


def test_source_satisfies_the_protocol():
    assert isinstance(SOURCE, PriceSource)
    assert SOURCE.kind == "hotel"
    assert SOURCE.estimate_calls(watch_for(LUMEN_SUBJECT)) == 1


def test_builtin_registration_includes_the_hotel_source():
    assert "app.services.price_sources.hotel" in price_watch.SOURCE_MODULES
    assert "hotel" in price_watch.register_builtin_sources()
    assert price_watch.get_source("hotel") is SOURCE


def test_serp_client_has_public_names():
    assert serp_flights.SERP_URL == "https://serpapi.com/search"
    assert serp_flights._SERP_URL == serp_flights.SERP_URL
    assert serp_flights.get_serp_client() is serp_flights.get_serp_client()
    assert hotel_prices.get_serp_client is serp_flights.get_serp_client


# ── Spec validation / match key ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "  "},
        {"city": ""},
        {"name": "x" * 201},
        {"city": "x" * 121},
        {"check_in": "10/12/2026"},
        {"check_out": "soon"},
        {"check_out": "2026-12-10"},  # same day
        {"check_out": "2026-12-01"},  # before check-in
        {"check_in": "2026-11-01", "check_out": "2026-11-05"},  # past
        {"check_in": "2026-11-04", "check_out": "2026-11-06"},  # today
        {"check_out": "2027-01-20"},  # > 30 nights
        {"adults": 0},
        {"adults": 17},
        {"adults": "two"},
        {"adults": True},
        {"rooms": 0},
        {"rooms": 9},
        {"rooms": 3},  # more rooms than adults
        {"property_token": 12},
        {"property_token": "t" * 301},
        {"estimate_total": -5},
        {"estimate_total": "lots"},
    ],
)
def test_invalid_specs_raise(bad):
    with pytest.raises(InvalidSpec):
        SOURCE.match_key(spec(**bad))


def test_missing_fields_raise():
    for field in ("name", "city", "check_in", "check_out", "adults"):
        s = spec()
        del s[field]
        with pytest.raises(InvalidSpec):
            SOURCE.match_key(s)


def test_match_key_is_normalised_and_covers_the_stay():
    key = SOURCE.match_key(spec())
    assert key == "lumen hotel|lisbon|2026-12-10|2026-12-14|2|1"
    assert SOURCE.match_key(spec(name="  LUMEN   hotel ", city="lisbon")) == key
    assert SOURCE.match_key(spec(name="Lúmen Hotel")) == key
    assert SOURCE.match_key(spec(rooms=1, property_token="abc")) == key
    assert SOURCE.match_key(spec(adults=3)) != key
    assert SOURCE.match_key(spec(rooms=2)) != key
    assert SOURCE.match_key(spec(check_out="2026-12-15")) != key


def test_numeric_strings_are_accepted():
    assert SOURCE.match_key(spec(adults="2", rooms="1")) == SOURCE.match_key(spec())


# ── Create ────────────────────────────────────────────────────────────────────


async def test_create_matches_the_named_hotel_and_prices_it_by_token():
    with serp(
        load("named_search_lumen_single_property.json"),
        load("property_details_lumen_generic_q.json"),
    ) as call:
        result = await SOURCE.create(spec(estimate_total=420), USER, "k")
    assert isinstance(result, CreatedWatch)
    assert call.await_count == 2
    search, price = (c.args[0] for c in call.await_args_list)
    assert search["q"] == "Lumen Hotel Lisbon"
    assert price["property_token"] == LUMEN_TOKEN
    assert result.subject == LUMEN_SUBJECT
    assert result.title == "Lumen Hotel & The Lisbon Light Show"
    assert result.subtitle == "10–14 Dec · 2 adults"
    assert result.expires_on == "2026-12-10"
    b = result.baseline
    # The baseline comes from the same property look every check uses
    assert (b.price, b.unit_price, b.status) == (368.0, 92.0, "ok")
    assert b.source == "google_hotels"
    assert b.link == "https://www.lumenhotel.pt/"
    assert b.calls == 2
    assert b.observed["name"] == "Lumen Hotel & The Lisbon Light Show"
    assert b.observed["nights"] == 4
    assert b.observed["nightly"] == 92.0
    assert b.observed["currency"] == "USD"
    assert b.observed["estimate_total"] == 420.0
    json.dumps(b.observed)


async def test_create_from_a_picked_suggestion_prices_the_token_directly():
    with serp(load("property_details_browns.json")) as call:
        result = await SOURCE.create(
            spec(
                name="Brown's | Avenue Hotel",
                check_in="2027-01-14",
                check_out="2027-01-17",
                property_token=BROWNS_TOKEN,
            ),
            USER,
            "k",
        )
    assert call.await_count == 1
    assert call.await_args.args[0]["property_token"] == BROWNS_TOKEN
    assert isinstance(result, CreatedWatch)
    assert result.subject["property_token"] == BROWNS_TOKEN
    assert result.title == "Brown's | Avenue Hotel"
    assert result.subtitle == "14–17 Jan · 2 adults"
    assert (result.baseline.price, result.baseline.unit_price) == (476.0, 159.0)
    assert result.baseline.calls == 1


async def test_create_with_rooms_says_so_in_the_subtitle():
    with serp(load("property_details_browns.json")):
        result = await SOURCE.create(
            spec(
                name="Brown's | Avenue Hotel",
                check_in="2027-01-14",
                check_out="2027-01-17",
                adults=4,
                rooms=2,
                property_token=BROWNS_TOKEN,
            ),
            USER,
            "k",
        )
    assert result.subtitle == "14–17 Jan · 4 adults · 2 rooms"
    assert result.subject["rooms"] == 2
    assert result.baseline.price == 952.0


async def test_create_without_a_confident_match_offers_priced_suggestions():
    with serp(load("city_search_lisbon.json")) as call:
        result = await SOURCE.create(
            spec(name="Lisbon Light Hotel", estimate_total=410), USER, "k"
        )
    assert call.await_count == 1
    assert isinstance(result, NoLivePrice)
    assert result.message == NO_LIVE
    assert result.calls == 1
    assert result.estimate == {
        "price": 410.0,
        "source": "ai_estimate",
        "label": "AI estimate",
    }
    assert 1 <= len(result.suggestions) <= 3
    for s in result.suggestions:
        assert s["title"] and s["price"] > 0 and s["nightly"] > 0
        assert s["currency"] == "USD"
        assert s["spec"]["property_token"]
        assert s["spec"]["name"] == s["title"]
        assert s["spec"]["city"] == "Lisbon"
        assert (s["spec"]["check_in"], s["spec"]["check_out"]) == (
            "2026-12-10",
            "2026-12-14",
        )
        assert (s["spec"]["adults"], s["spec"]["rooms"]) == (2, 1)
        assert s["subtitle"].endswith("a night · total for 4 nights")
        # A suggestion's spec is itself a valid spec
        SOURCE.match_key(s["spec"])
    assert result.suggestions[0]["title"] == "Lumen Hotel & The Lisbon Light Show"


async def test_create_with_no_results_has_no_suggestions_and_no_estimate():
    with serp(load("synthetic_no_results.json")):
        result = await SOURCE.create(spec(name="Zzyzx Nonexistent Hotel"), USER, "k")
    assert isinstance(result, NoLivePrice)
    assert result.message == NO_LIVE
    assert result.suggestions == [] and result.estimate is None


async def test_create_when_the_matched_property_has_no_rates():
    no_rates = load("property_details_no_rates.json")
    with serp(load("named_search_lumen_single_property.json"), no_rates):
        result = await SOURCE.create(spec(), USER, "k")
    assert isinstance(result, NoLivePrice)
    assert result.message == NO_LIVE
    assert result.calls == 2


async def test_create_from_a_sold_out_suggestion_is_no_live_price():
    with serp(load("property_details_no_rates.json")):
        result = await SOURCE.create(
            spec(property_token="ChkIn4CU6sjxgJ1YGg0vZy8xMWY0XzdqenhqEAE"), USER, "k"
        )
    assert isinstance(result, NoLivePrice)
    assert result.calls == 1


async def test_cached_looks_spend_no_calls():
    responses = (
        load("named_search_lumen_single_property.json"),
        load("property_details_lumen_generic_q.json"),
    )
    with serp(*responses):
        await SOURCE.create(spec(), USER, "k")
    with serp() as call:
        again = await SOURCE.create(spec(), USER, "k")
    assert call.await_count == 0
    assert again.baseline.calls == 0


async def test_create_validates_before_any_call():
    with serp() as call, pytest.raises(InvalidSpec):
        await SOURCE.create(spec(adults=0), USER, "k")
    assert call.await_count == 0


async def test_create_passes_errors_through():
    with patch.object(
        hotel_prices,
        "_call",
        AsyncMock(side_effect=hotel_prices.SerpAPIError("boom", quota_exceeded=True)),
    ):
        with pytest.raises(hotel_prices.SerpAPIError) as info:
            await SOURCE.create(spec(), USER, "k")
    assert info.value.quota_exceeded is True


# ── Check ─────────────────────────────────────────────────────────────────────


async def test_check_prices_the_stored_property():
    with serp(load("property_details_lumen_generic_q.json")) as call:
        obs = await SOURCE.check(watch_for(LUMEN_SUBJECT), "k")
    params = call.await_args.args[0]
    assert params["property_token"] == LUMEN_TOKEN
    assert (params["check_in_date"], params["check_out_date"]) == (
        "2026-12-10",
        "2026-12-14",
    )
    assert params["adults"] == "2"
    assert isinstance(obs, PriceObservation)
    assert (obs.price, obs.unit_price, obs.status) == (368.0, 92.0, "ok")
    assert obs.source == "google_hotels" and obs.calls == 1
    assert obs.link == "https://www.lumenhotel.pt/"
    assert obs.observed["nightly"] == 92.0


async def test_check_sold_out_is_unavailable_not_an_error():
    subject = {
        **LUMEN_SUBJECT,
        "property_token": "ChkIn4CU6sjxgJ1YGg0vZy8xMWY0XzdqenhqEAE",
    }
    with serp(load("property_details_no_rates.json")):
        obs = await SOURCE.check(watch_for(subject), "k")
    assert obs.status == "unavailable" and obs.price is None
    assert obs.source == "google_hotels" and obs.calls == 1


async def test_check_raises_on_serpapi_errors():
    with patch.object(
        hotel_prices, "_call", AsyncMock(side_effect=hotel_prices.SerpAPIError("x"))
    ):
        with pytest.raises(hotel_prices.SerpAPIError):
            await SOURCE.check(watch_for(LUMEN_SUBJECT), "k")


# ── Wording ───────────────────────────────────────────────────────────────────


def test_compose_drop_copy():
    w = watch_for({**LUMEN_SUBJECT, "name": "Lumen Hotel"}, title="Lumen Hotel")
    obs = PriceObservation(price=352.0, unit_price=88.0, source="google_hotels")
    note = SOURCE.compose("hotel_drop", w, obs, 398.0)
    assert note["kind"] == "hotel_drop"
    assert note["title"] == "🏨 Lumen Hotel dropped to $352 for 10–14 Dec (−$46)"
    assert "$88 a night" in note["body"]
    assert "4 nights" in note["body"] and "2 adults" in note["body"]
    assert "Google Hotels" in note["body"]
    assert note["data"]["nightly"] == 88.0
    assert note["data"]["check_in"] == "2026-12-10"


def test_compose_target_copy():
    w = watch_for(
        {**LUMEN_SUBJECT, "name": "Lumen Hotel"},
        title="Lumen Hotel",
        target_price=360.0,
        alert_mode="below_target",
    )
    obs = PriceObservation(price=352.0, unit_price=88.0, source="google_hotels")
    note = SOURCE.compose("hotel_target", w, obs, 398.0)
    assert note["title"] == "🏨 Lumen Hotel is now $352 — below your $360 target"
    assert "$88 a night" in note["body"]


def test_compose_says_when_it_is_the_lowest_seen():
    w = watch_for(LUMEN_SUBJECT, lowest_price=360.0)
    obs = PriceObservation(price=352.0, unit_price=88.0)
    assert "lowest we've seen" in SOURCE.compose("hotel_drop", w, obs, 398.0)["body"]
    w = watch_for(LUMEN_SUBJECT, lowest_price=300.0)
    assert "lowest" not in SOURCE.compose("hotel_drop", w, obs, 398.0)["body"]


def test_compose_one_night_one_adult_and_cross_month():
    subject = {
        **LUMEN_SUBJECT,
        "check_in": "2026-12-31",
        "check_out": "2027-01-01",
        "adults": 1,
    }
    w = watch_for(subject, title="Lumen")
    obs = PriceObservation(price=90.0, unit_price=90.0)
    note = SOURCE.compose("hotel_drop", w, obs, 120.0)
    assert "31 Dec 2026 – 1 Jan 2027" in note["title"]
    assert "1 night" in note["body"] and "1 adult" in note["body"]
    assert "nights" not in note["body"] and "adults" not in note["body"]


def test_helpers_module_exposes_the_message():
    assert hotel.NO_LIVE_PRICE_MESSAGE == NO_LIVE
