"""Unit tests for the live hotel price adapter (SerpAPI Google Hotels).

All SerpAPI responses come from fixtures recorded live on 2026-11-04 under
tests/fixtures/serpapi/hotels/ (api key stripped); ``synthetic_*`` fixtures
are hand-made. No test touches the network.
"""

import copy
import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import hotel_prices
from app.services.hotel_prices import (
    MATCH_THRESHOLD,
    HotelOffer,
    HotelPrice,
    SerpAPIError,
    find_properties,
    match_property,
    name_similarity,
    price_property,
    suggestions,
)

FIXTURES = Path(__file__).parent / "fixtures" / "serpapi" / "hotels"
API_KEY = "secret-test-key"
LUMEN_TOKEN = "ChoIkamS5OLO9d2QARoNL2cvMTFrODM4N24zORAB"
BROWNS_TOKEN = "ChkIhLCQwvjO2IYWGg0vZy8xMXE0bTZieDkyEAE"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def clear_cache():
    from app.core.cache import get_cache

    get_cache().clear()
    yield
    get_cache().clear()


def mock_call(*responses):
    """Patch the SerpAPI call to return ``responses`` in order (deep copies)."""
    return patch.object(
        hotel_prices,
        "_call",
        AsyncMock(side_effect=[copy.deepcopy(r) for r in responses]),
    )


def offer(name: str, total: float | None = 400.0, token: str | None = None):
    return HotelOffer(
        name=name,
        property_token=token or f"tok-{name}",
        rate_per_night=None if total is None else total / 4,
        total_rate=total,
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


# ── Fixture hygiene ───────────────────────────────────────────────────────────


def test_fixtures_carry_no_api_key():
    files = sorted(FIXTURES.glob("*.json"))
    assert len(files) >= 5
    for f in files:
        text = f.read_text()
        assert "api_key" not in text, f.name
        meta = json.loads(text).get("search_metadata", {})
        assert "json_endpoint" not in meta and "raw_html_file" not in meta


# ── find_properties: city search (properties list) ───────────────────────────


async def test_city_search_parses_every_property():
    with mock_call(load("city_search_lisbon.json")):
        offers = await find_properties(
            "hotels in", "Lisbon", "2026-12-10", "2026-12-14", 2, API_KEY
        )
    assert len(offers) == 20
    assert all(o.property_token for o in offers)
    lumen = next(o for o in offers if o.name.startswith("Lumen"))
    assert lumen.name == "Lumen Hotel & The Lisbon Light Show"
    assert lumen.rate_per_night == 100
    assert lumen.total_rate == 398
    assert lumen.currency == "USD"
    assert lumen.hotel_class == 4
    assert lumen.overall_rating == 4.6
    assert lumen.reviews == 1405
    assert lumen.gps == {
        "lat": pytest.approx(38.7295874, abs=1e-3),
        "lng": pytest.approx(-9.1456, abs=1e-3),
    }
    assert (lumen.check_in, lumen.check_out, lumen.adults) == (
        "2026-12-10",
        "2026-12-14",
        2,
    )
    # Vacation rentals have no hotel class; a missing website falls back to Google
    tandem = next(o for o in offers if o.name.startswith("Tandem"))
    assert tandem.hotel_class is None
    assert tandem.link and tandem.link.startswith("https://www.google.com/travel")


async def test_city_search_sends_expected_params_and_key():
    with mock_call(load("city_search_lisbon.json")) as call:
        await find_properties(
            "Lumen Hotel", "Lisbon", date(2026, 12, 10), date(2026, 12, 14), 2, API_KEY
        )
    params = call.await_args.args[0]
    assert params == {
        "engine": "google_hotels",
        "q": "Lumen Hotel Lisbon",
        "check_in_date": "2026-12-10",
        "check_out_date": "2026-12-14",
        "adults": "2",
        "currency": "USD",
        "hl": "en",
        "gl": "us",
        "api_key": API_KEY,
    }


# ── find_properties: direct property match (single property page) ────────────


async def test_named_search_single_property_shape():
    with mock_call(load("named_search_lumen_single_property.json")):
        offers = await find_properties(
            "Lumen Hotel", "Lisbon", "2026-12-10", "2026-12-14", 2, API_KEY
        )
    assert len(offers) == 1
    o = offers[0]
    assert o.name == "Lumen Hotel & The Lisbon Light Show"
    assert o.property_token == LUMEN_TOKEN
    assert (o.rate_per_night, o.total_rate) == (100, 398)
    assert o.link == "https://www.lumenhotel.pt/"
    assert match_property("Lumen Hotel", offers, city="Lisbon") is o


async def test_no_results_returns_empty_list():
    with mock_call(load("synthetic_no_results.json")):
        offers = await find_properties(
            "Zzyzx Nonexistent Hotel", "Lisbon", "2026-12-10", "2026-12-14", 2, API_KEY
        )
    assert offers == []


async def test_other_serpapi_error_raises():
    with mock_call({"error": "Invalid API key. Your API key should be here"}):
        with pytest.raises(SerpAPIError):
            await find_properties("X", "Lisbon", "2026-12-10", "2026-12-14", 2, API_KEY)


async def test_missing_fields_are_tolerated():
    data = {
        "properties": [
            {"name": "No Price Inn", "property_token": "t1"},
            {
                "name": "Half Priced",
                "property_token": "t2",
                "rate_per_night": {"extracted_lowest": 50},
            },
            {
                "name": "Only Total",
                "property_token": "t3",
                "total_rate": {"lowest": "$1,200"},
            },
            {"name": "No Token Hotel"},
            {"property_token": "t4"},
            "garbage",
            {
                "name": "Bad Types",
                "property_token": "t5",
                "rate_per_night": "cheap",
                "total_rate": {"extracted_lowest": True},
                "gps_coordinates": "x",
                "overall_rating": "great",
                "reviews": None,
                "extracted_hotel_class": "4",
            },
        ]
    }
    with mock_call(data):
        offers = await find_properties(
            "x", "Lisbon", "2026-12-10", "2026-12-14", 2, API_KEY
        )
    by_name = {o.name: o for o in offers}
    assert set(by_name) == {"No Price Inn", "Half Priced", "Only Total", "Bad Types"}
    assert by_name["No Price Inn"].total_rate is None
    assert by_name["No Price Inn"].rate_per_night is None
    # Missing total is derived from nightly × nights (4 nights) and vice versa
    assert by_name["Half Priced"].total_rate == 200
    assert by_name["Only Total"].total_rate == 1200
    assert by_name["Only Total"].rate_per_night == 300
    bad = by_name["Bad Types"]
    assert (
        bad.total_rate,
        bad.rate_per_night,
        bad.gps,
        bad.overall_rating,
        bad.reviews,
        bad.hotel_class,
    ) == (None, None, None, None, None, None)


async def test_rooms_multiply_prices_and_split_adults():
    with mock_call(load("named_search_lumen_single_property.json")) as call:
        offers = await find_properties(
            "Lumen Hotel", "Lisbon", "2026-12-10", "2026-12-14", 3, API_KEY, rooms=2
        )
    assert call.await_args.args[0]["adults"] == "2"  # ceil(3 / 2) per room
    assert offers[0].total_rate == 796
    assert offers[0].rate_per_night == 200
    assert offers[0].adults == 3


async def test_invalid_dates_raise_value_error():
    with pytest.raises(ValueError):
        await find_properties("x", "Lisbon", "2026-12-14", "2026-12-10", 2, API_KEY)
    with pytest.raises(ValueError):
        await price_property("t", "2026-12-10", "2026-12-10", 2, API_KEY)
    with pytest.raises(ValueError):
        await price_property("t", "2026-12-10", "2026-12-12", 0, API_KEY)


# ── match_property ────────────────────────────────────────────────────────────


@pytest.fixture
def lisbon_offers():
    data = load("city_search_lisbon.json")
    return [
        hotel_prices._parse_property(p, data, "2026-12-10", "2026-12-14", 2, 1)
        for p in data["properties"]
    ]


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Lumen Hotel", "Lumen Hotel & The Lisbon Light Show"),
        ("Lumen Hotel Lisboa", "Lumen Hotel & The Lisbon Light Show"),
        ("LUMEN HOTEL & THE LISBON LIGHT SHOW", "Lumen Hotel & The Lisbon Light Show"),
        ("Brown's Avenue Hotel", "Brown's | Avenue Hotel"),
        ("Eurostars Das Letras", "Eurostars das Letras"),
        ("The One Palacio da Anunciada", "The One Palácio da Anunciada"),
        ("Pestana Rua Augusta Hotel", "Pestana Rua Augusta"),
        (
            "Holiday Inn Express Lisbon",
            "Holiday Inn Express Lisbon - Ave. Liberdade by IHG",
        ),
        ("Hotel Marques de Pombal", "Hotel Marquês de Pombal"),
    ],
)
def test_match_property_accepts_real_names(lisbon_offers, name, expected):
    match = match_property(name, lisbon_offers, city="Lisbon")
    assert match is not None and match.name == expected


@pytest.mark.parametrize(
    "name",
    [
        "Lisbon Light Hotel",  # shares "light" with Lumen … Light Show
        "Hotel Lisbon",  # nothing distinctive left
        "Hotel",
        "",
        "My Story Hotel Tejo",  # same chain, different property
        "Pestana Palace",  # same chain, different property
        "Avenida Palace",
        "Baixa House",  # shares "baixa" with Hotel da Baixa / Be Poet Baixa
        "Four Seasons Hotel Ritz Lisbon",
    ],
)
def test_match_property_rejects_near_misses(lisbon_offers, name):
    assert match_property(name, lisbon_offers, city="Lisbon") is None


def test_lisbon_light_vs_lumen_without_city_still_rejected():
    o = offer("Lumen Hotel & The Lisbon Light Show")
    assert match_property("Lisbon Light Hotel", [o]) is None
    assert match_property("Lisbon Light Hotel", [offer("Lumen Hotel")]) is None


def test_threshold_boundaries():
    assert MATCH_THRESHOLD == 0.6
    # 2 of 3 distinctive words shared → 0.67, accepted
    assert (
        name_similarity("Story Rossio Hotel", "My Story Rossio Alfama")
        >= MATCH_THRESHOLD
    )
    # 1 of 2 → 0.5, rejected
    assert name_similarity("Hotel da Baixa", "Be Poet Baixa Hotel") < MATCH_THRESHOLD
    assert name_similarity("Lumen", "Lumen") == 1.0
    assert name_similarity("Hotel", "Hotel") == 0.0


def test_match_prefers_best_score():
    offers = [
        offer("Pestana Rua Augusta Lisbon Downtown"),
        offer("Pestana Rua Augusta"),
    ]
    assert match_property("Pestana Rua Augusta", offers).name == "Pestana Rua Augusta"


def test_match_property_empty_offers():
    assert match_property("Lumen Hotel", []) is None


# ── price_property ────────────────────────────────────────────────────────────


async def test_price_property_details():
    with mock_call(load("property_details_browns.json")) as call:
        price = await price_property(
            BROWNS_TOKEN, "2027-01-14", "2027-01-17", 2, API_KEY
        )
    params = call.await_args.args[0]
    assert params["property_token"] == BROWNS_TOKEN
    assert params["engine"] == "google_hotels"
    assert params["check_in_date"] == "2027-01-14"
    assert params["check_out_date"] == "2027-01-17"
    assert params["currency"] == "USD" and params["gl"] == "us" and params["hl"] == "en"
    assert params["q"]  # SerpAPI requires q even with a property token
    assert isinstance(price, HotelPrice)
    assert price.available is True
    assert price.total == 476
    assert price.nightly == 159
    assert price.link == "https://www.brownshotelgroup.com/browns-avenue/"
    obs = price.observed
    assert obs["source"] == "google_hotels"
    assert obs["name"] == "Brown's | Avenue Hotel"
    assert obs["property_token"] == BROWNS_TOKEN
    assert obs["currency"] == "USD"
    assert obs["check_in"] == "2027-01-14" and obs["nights"] == 3
    assert obs["observed_at"]
    assert obs["total_rate"]["extracted_lowest"] == 476


async def test_price_property_no_rates_is_unavailable_not_error():
    data = load("property_details_no_rates.json")
    token = data["property_token"]
    with mock_call(data):
        price = await price_property(token, "2026-12-30", "2027-01-02", 6, API_KEY)
    assert price.available is False
    assert price.total is None and price.nightly is None
    assert price.observed["name"] == "Patio São Vicente Guest Houses"


async def test_price_property_no_results_is_unavailable():
    with mock_call(load("synthetic_no_results.json")):
        price = await price_property("tok", "2026-12-10", "2026-12-14", 2, API_KEY)
    assert price.available is False


async def test_price_property_list_shape_finds_token_or_unavailable():
    data = load("city_search_lisbon.json")
    with mock_call(data):
        price = await price_property(
            LUMEN_TOKEN, "2026-12-10", "2026-12-14", 2, API_KEY
        )
    assert price.available and price.total == 398
    with mock_call(data):
        price = await price_property("unknown", "2026-12-11", "2026-12-14", 2, API_KEY)
    assert price.available is False


async def test_price_property_rooms():
    with mock_call(load("property_details_browns.json")) as call:
        price = await price_property(
            BROWNS_TOKEN, "2027-01-14", "2027-01-17", 4, API_KEY, rooms=2
        )
    assert call.await_args.args[0]["adults"] == "2"
    assert price.total == 952 and price.nightly == 318
    assert price.observed["rooms"] == 2


async def test_price_property_error_payload_raises():
    with mock_call({"error": "Invalid property token."}):
        with pytest.raises(SerpAPIError):
            await price_property("bad", "2026-12-10", "2026-12-14", 2, API_KEY)


# ── HTTP-level errors (_call) ─────────────────────────────────────────────────


def _client_returning(resp=None, exc=None):
    client = MagicMock()
    client.get = AsyncMock(return_value=resp, side_effect=exc)
    return client


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("slow"), httpx.ConnectError("down")])
async def test_transport_errors_raise_serpapi_error(exc):
    with patch.object(
        hotel_prices, "get_serp_client", return_value=_client_returning(exc=exc)
    ):
        with pytest.raises(SerpAPIError):
            await price_property("t", "2026-12-10", "2026-12-14", 2, API_KEY)


async def test_quota_and_http_errors():
    resp = httpx.Response(429, text="too many")
    with patch.object(
        hotel_prices, "get_serp_client", return_value=_client_returning(resp)
    ):
        with pytest.raises(SerpAPIError) as info:
            await find_properties("x", "Lisbon", "2026-12-10", "2026-12-14", 2, API_KEY)
    assert info.value.quota_exceeded is True
    resp = httpx.Response(500, text="boom")
    with patch.object(
        hotel_prices, "get_serp_client", return_value=_client_returning(resp)
    ):
        with pytest.raises(SerpAPIError) as info:
            await price_property("t", "2026-12-10", "2026-12-14", 2, API_KEY)
    assert info.value.quota_exceeded is False


async def test_non_json_body_raises_serpapi_error():
    resp = httpx.Response(200, text="<html>oops</html>")
    with patch.object(
        hotel_prices, "get_serp_client", return_value=_client_returning(resp)
    ):
        with pytest.raises(SerpAPIError):
            await price_property("t", "2026-12-10", "2026-12-14", 2, API_KEY)


async def test_http_error_text_never_leaks_api_key():
    resp = httpx.Response(401, text=f"bad key {API_KEY}")
    with patch.object(
        hotel_prices, "get_serp_client", return_value=_client_returning(resp)
    ):
        with pytest.raises(SerpAPIError) as info:
            await price_property("t", "2026-12-10", "2026-12-14", 2, API_KEY)
    assert API_KEY not in str(info.value)


# ── Caching ───────────────────────────────────────────────────────────────────


async def test_find_properties_cached_and_keyed_without_api_key():
    from app.core.cache import get_cache

    with mock_call(load("city_search_lisbon.json")) as call:
        a = await find_properties(
            "hotels in", "Lisbon", "2026-12-10", "2026-12-14", 2, API_KEY
        )
        b = await find_properties(
            "hotels in", "Lisbon", "2026-12-10", "2026-12-14", 2, "other-key"
        )
    assert call.await_count == 1
    assert a == b
    keys = [
        k for k in get_cache() if isinstance(k, str) and k.startswith("serp-hotels:")
    ]
    assert len(keys) == 1
    assert API_KEY not in keys[0] and "other-key" not in keys[0]


async def test_cache_key_covers_every_parameter():
    variants = [
        ("hotels in", "Lisbon", "2026-12-10", "2026-12-14", 2, 1),
        ("hotels near", "Lisbon", "2026-12-10", "2026-12-14", 2, 1),
        ("hotels in", "Porto", "2026-12-10", "2026-12-14", 2, 1),
        ("hotels in", "Lisbon", "2026-12-11", "2026-12-14", 2, 1),
        ("hotels in", "Lisbon", "2026-12-10", "2026-12-15", 2, 1),
        ("hotels in", "Lisbon", "2026-12-10", "2026-12-14", 3, 1),
        ("hotels in", "Lisbon", "2026-12-10", "2026-12-14", 2, 2),
    ]
    data = load("city_search_lisbon.json")
    with mock_call(*[data] * len(variants)) as call:
        for name, city, ci, co, adults, rooms in variants:
            await find_properties(name, city, ci, co, adults, API_KEY, rooms=rooms)
    assert call.await_count == len(variants)


async def test_price_property_cached_by_all_params_without_key():
    from app.core.cache import get_cache

    data = load("property_details_browns.json")
    with mock_call(data, data, data) as call:
        p1 = await price_property(BROWNS_TOKEN, "2027-01-14", "2027-01-17", 2, API_KEY)
        p2 = await price_property(BROWNS_TOKEN, "2027-01-14", "2027-01-17", 2, "k2")
        await price_property(BROWNS_TOKEN, "2027-01-14", "2027-01-17", 3, API_KEY)
        await price_property(
            BROWNS_TOKEN, "2027-01-14", "2027-01-17", 2, API_KEY, rooms=2
        )
    assert call.await_count == 3
    assert p1 == p2
    for k in get_cache():
        assert API_KEY not in str(k) and "k2" not in str(k)


async def test_errors_are_not_cached():
    with patch.object(
        hotel_prices,
        "_call",
        AsyncMock(
            side_effect=[SerpAPIError("timeout"), load("property_details_browns.json")]
        ),
    ):
        with pytest.raises(SerpAPIError):
            await price_property(BROWNS_TOKEN, "2027-01-14", "2027-01-17", 2, API_KEY)
        price = await price_property(
            BROWNS_TOKEN, "2027-01-14", "2027-01-17", 2, API_KEY
        )
    assert price.available


# ── suggestions ───────────────────────────────────────────────────────────────


def test_suggestions_only_priced_and_capped(lisbon_offers):
    out = suggestions(lisbon_offers)
    assert len(out) == 3
    assert all(o.total_rate for o in out)
    assert [o.name for o in out] == [o.name for o in lisbon_offers[:3]]


def test_suggestions_skip_unpriced_and_duplicates():
    a = offer("A", token="t1")
    dup = offer("A again", token="t1")
    unpriced = offer("B", total=None, token="t2")
    c = offer("C", token="t3")
    assert suggestions([unpriced, a, dup, c], n=3) == [a, c]
    assert suggestions([], n=3) == []
    assert suggestions([a, c], n=0) == []


def test_suggestions_rank_by_similarity_when_name_given(lisbon_offers):
    out = suggestions(lisbon_offers, n=2, name="Lisbon Light Hotel")
    assert out[0].name == "Lumen Hotel & The Lisbon Light Show"


async def test_price_property_generic_query_fixture():
    """Recorded with q="hotel": the token alone selects the property."""
    with mock_call(load("property_details_lumen_generic_q.json")) as call:
        price = await price_property(
            LUMEN_TOKEN, "2026-12-10", "2026-12-14", 2, API_KEY
        )
    assert call.await_args.args[0]["q"] == "hotel"
    assert price.available and price.total == 368
    assert price.observed["name"] == "Lumen Hotel & The Lisbon Light Show"


async def test_cached_price_observed_is_a_copy():
    data = load("property_details_browns.json")
    with mock_call(data):
        p1 = await price_property(BROWNS_TOKEN, "2027-01-14", "2027-01-17", 2, API_KEY)
        p1.observed["name"] = "mutated"
        p2 = await price_property(BROWNS_TOKEN, "2027-01-14", "2027-01-17", 2, API_KEY)
    assert p2.observed["name"] == "Brown's | Avenue Hotel"
