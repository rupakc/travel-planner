"""Tests for the trip-comparison summary and /api/compare/destination."""

import asyncio
import math
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.request import TravelSearchRequest
from app.services.compare import summarize_destination


def _req(**kw) -> TravelSearchRequest:
    base = dict(
        origin="JFK",
        destination="Tokyo",
        departure_date=date(2026, 4, 1),
        return_date=date(2026, 4, 8),
        nationality="American",
        num_travelers=1,
    )
    base.update(kw)
    return TravelSearchRequest(**base)


def _fare(price, source="google_flights", out=(0, 600), ret=(1, 700), airline="ANA"):
    return {
        "price_usd": price,
        "source": source,
        "outbound": {
            "airline": airline,
            "stops": out[0],
            "duration_minutes": out[1],
            "destination": "Tokyo, Japan",
        },
        "return": {"stops": ret[0], "duration_minutes": ret[1]},
    }


def _hotel(price, stars, review=8.0):
    return {"price_per_night_usd": price, "star_rating": stars, "review_score": review}


def _no_nan(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            _no_nan(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_nan(v)
    elif isinstance(obj, float):
        assert math.isfinite(obj)


@pytest.fixture(autouse=True)
def _db(client):
    """The request model validates airports; the app fixture initialises that DB."""


class TestSummarize:
    def test_cheapest_fare_sums_legs(self):
        flights = {"results": [_fare(900), _fare(700, out=(1, 500), ret=(2, 400))]}
        s = summarize_destination(_req(), flights, None, None, None, None)
        assert s["flight"] == {
            "price_usd": 700,
            "stops": 3,
            "duration_minutes": 900,
            "airline": "ANA",
            "source": "google_flights",
        }
        assert s["label"] == "Tokyo"

    def test_estimates_deprioritised_but_used_alone(self):
        mixed = {"results": [_fare(300, source="estimate"), _fare(800)]}
        assert (
            summarize_destination(_req(), mixed, None, None, None, None)["flight"][
                "price_usd"
            ]
            == 800
        )
        only = {"results": [_fare(300, source="estimate")]}
        f = summarize_destination(_req(), only, None, None, None, None)["flight"]
        assert f["price_usd"] == 300 and f["source"] == "estimate"

    def test_junk_fares_ignored(self):
        flights = {
            "results": [
                _fare("abc"),
                _fare(-5),
                _fare(0),
                _fare(float("nan")),
                _fare(float("inf")),
                _fare(None),
                "garbage",
                _fare("450.5"),
            ]
        }
        s = summarize_destination(_req(), flights, None, None, None, None)
        assert s["flight"]["price_usd"] == 450.5

    def test_missing_return_leg(self):
        fare = _fare(500)
        del fare["return"]
        s = summarize_destination(_req(), {"results": [fare]}, None, None, None, None)
        assert s["flight"]["stops"] == 0
        assert s["flight"]["duration_minutes"] == 600

    def test_hotel_median_of_3_to_4_stars_and_cheapest_good(self):
        hotels = {
            "results": [
                _hotel(500, 5),
                _hotel(100, 3, review=6.5),
                _hotel(200, 4),
                _hotel(300, 4),
                _hotel(40, 2, review=7.0),
            ]
        }
        h = summarize_destination(_req(), None, hotels, None, None, None)["hotel"]
        assert h["typical_nightly_usd"] == 200  # median(100, 200, 300)
        assert h["cheapest_good_nightly_usd"] == 40
        assert h["count"] == 5

    def test_hotel_fallback_all_priced_and_no_good_reviews(self):
        hotels = {"results": [_hotel(50, 2, review=5), _hotel(150, 5, review="x")]}
        h = summarize_destination(_req(), None, hotels, None, None, None)["hotel"]
        assert h["typical_nightly_usd"] == 100
        assert h["cheapest_good_nightly_usd"] is None

    def test_weather_averages_and_poor_days(self):
        weather = {
            "source": "open-meteo",
            "days": [
                {"temp_high_c": 20, "temp_low_c": 10, "is_poor": False},
                {"temp_high_c": 25, "temp_low_c": 14, "is_poor": True},
                {"temp_high_c": "bad", "temp_low_c": None, "is_poor": True},
            ],
        }
        w = summarize_destination(_req(), None, None, weather, None, None)["weather"]
        assert w == {
            "avg_high_c": 22.5,
            "avg_low_c": 12.0,
            "poor_days": 2,
            "total_days": 3,
            "source": "open-meteo",
        }

    def test_visa_verified_flag(self):
        visa = {
            "requirement": {
                "visa_type": "visa-free",
                "max_stay_days": 90,
                "fee_usd": 0,
                "processing_time": "none",
            }
        }
        s = summarize_destination(_req(), None, None, None, visa, None)
        assert s["visa"]["verified"] is False
        assert s["visa"]["fee_usd"] == 0
        s = summarize_destination(
            _req(), None, None, None, visa, None, visa_verified=True
        )
        assert s["visa"]["verified"] is True and s["visa"]["max_stay_days"] == 90

    def test_ease_sub_scores(self):
        conf = {
            "total": 80,
            "grade": "green",
            "sub_scores": {
                "visa_ease": {"score": 20},
                "safety": {"score": 19},
                "english_friendliness": {"score": 8},
                "tourist_infrastructure": {"score": 20},
            },
        }
        e = summarize_destination(_req(), None, None, None, None, conf)["ease"]
        assert e == {
            "total": 80,
            "grade": "green",
            "safety": 19,
            "english": 8,
            "infrastructure": 20,
            "visa_ease": 20,
        }

    def test_estimate_daily_spend_is_all_in(self):
        # avg_daily_cost_usd is an all-in daily budget (lodging included), so the
        # stay is shown for reference but not added to the total.
        flights = {"results": [_fare(1000)]}
        hotels = {"results": [_hotel(100, 3)]}
        s = summarize_destination(
            _req(budget_usd=5000), flights, hotels, None, None, None
        )
        est = s["estimate"]
        assert s["daily_cost_usd"] == 120  # Tokyo -> japan table
        assert est["nights"] == 7
        assert est["stay_usd"] == 700 and est["daily_usd"] == 840
        assert est["included_in_daily"] is True
        assert est["flight_usd"] == s["flight"]["price_usd"] == 1000
        assert est["total_usd"] == 1840 and est["partial"] is False
        assert est["budget_status"] == "under"
        over = summarize_destination(
            _req(budget_usd=1500), flights, hotels, None, None, None
        )
        assert over["estimate"]["budget_status"] == "over"
        none = summarize_destination(_req(), flights, hotels, None, None, None)
        assert none["estimate"]["budget_status"] is None

    def test_stay_counts_when_daily_spend_unknown(self):
        s = summarize_destination(
            _req(destination="Zzyzx Nowhere"),
            {"results": [_fare(400)]},
            {"results": [_hotel(100, 3)]},
            None,
            None,
            None,
        )
        est = s["estimate"]
        assert est["included_in_daily"] is False
        assert est["total_usd"] == 1100 and est["partial"] is True

    def test_budget_depends_on_party_size(self):
        flights = {"results": [_fare(1000)]}
        hotels = {"results": [_hotel(100, 3)]}
        one = summarize_destination(
            _req(budget_usd=3000), flights, hotels, None, None, None
        )
        two = summarize_destination(
            _req(budget_usd=3000, num_travelers=2), flights, hotels, None, None, None
        )
        assert one["estimate"]["budget_status"] == "under"
        assert two["estimate"]["budget_status"] == "over"

    def test_stay_cost_is_per_room_shared_by_two(self):
        hotels = {"results": [_hotel(100, 3)]}
        stay = {
            n: summarize_destination(
                _req(num_travelers=n), None, hotels, None, None, None
            )["estimate"]["stay_usd"]
            for n in (1, 2, 3, 4)
        }
        assert stay == {1: 700, 2: 350, 3: pytest.approx(466.67, abs=0.01), 4: 350}

    def test_rooms_come_from_adults_and_seniors(self):
        hotels = {"results": [_hotel(100, 3)]}

        def stay(**kw):
            return summarize_destination(_req(**kw), None, hotels, None, None, None)[
                "estimate"
            ]["stay_usd"]

        # 2 adults + 2 children share one room: 700 / 4 travellers
        assert stay(num_travelers=4, adults=2, children=2) == 175
        # 3 adults need two rooms: 1400 / 3
        assert stay(num_travelers=3, adults=3) == pytest.approx(466.67, abs=0.01)
        # 1 adult + 1 senior + 1 infant: one room over 3 travellers
        assert stay(num_travelers=3, adults=1, seniors=1, infants=1) == pytest.approx(
            233.33, abs=0.01
        )
        # adults/seniors explicitly zero -> fall back to num_travelers
        assert stay(num_travelers=4, adults=0, seniors=0, children=4) == 350

    def test_partial_budget_status(self):
        flights = {"results": [_fare(400)]}
        under = summarize_destination(
            _req(destination="Zzyzx Nowhere", budget_usd=5000),
            flights,
            None,
            None,
            None,
            None,
        )
        over = summarize_destination(
            _req(destination="Zzyzx Nowhere", budget_usd=100),
            flights,
            None,
            None,
            None,
            None,
        )
        assert under["estimate"]["partial"] is True
        assert under["estimate"]["budget_status"] is None
        assert over["estimate"]["budget_status"] == "over"

    def test_estimate_partial_for_unknown_destination(self):
        s = summarize_destination(
            _req(destination="Zzyzx Nowhere"),
            {"results": [_fare(400)]},
            None,
            None,
            None,
            None,
        )
        est = s["estimate"]
        assert s["daily_cost_usd"] is None and s["ease"] is None
        assert est["total_usd"] == 400 and est["partial"] is True
        assert est["stay_usd"] is None and est["daily_usd"] is None

    def test_default_nights_for_one_way(self):
        s = summarize_destination(_req(return_date=None), None, None, None, None, None)
        assert s["estimate"]["nights"] == 7

    def test_all_empty_inputs(self):
        for empty in (None, {}, {"results": []}, {"days": []}, "junk"):
            s = summarize_destination(
                _req(destination="Zzyzx Nowhere"), empty, empty, empty, empty, None
            )
            assert s["flight"] is None and s["hotel"] is None
            assert s["weather"] is None and s["visa"] is None
            assert s["estimate"]["total_usd"] is None
            assert s["estimate"]["partial"] is True
            _no_nan(s)

    def test_missing_lists_failed_pieces(self):
        s = summarize_destination(_req(), None, {"results": []}, None, {}, None)
        assert s["missing"] == ["flights", "weather"]


# ── Route ────────────────────────────────────────────────────────────────────

_PAYLOAD = {
    "origin": "JFK",
    "destination": "Tokyo",
    "departure_date": "2026-04-01",
    "return_date": "2026-04-08",
    "nationality": "American",
    "num_travelers": 1,
}
_FLIGHTS = {"results": [_fare(900)]}
_HOTELS = {"results": [_hotel(120, 3)]}
_WEATHER = {"source": "open-meteo", "days": [{"temp_high_c": 20, "temp_low_c": 12}]}
_VISA = {"requirement": {"visa_type": "e-visa", "max_stay_days": 30, "fee_usd": 50}}


@pytest.fixture
def agents():
    """Patch the four lazy agent factories with AsyncMock-backed fakes."""
    from app.core.cache import get_cache

    get_cache().clear()
    with (
        patch("app.api.routes.compare.get_flights_agent") as f,
        patch("app.api.routes.compare.get_hotels_agent") as h,
        patch("app.api.routes.compare.get_weather_agent") as w,
        patch("app.api.routes.compare.get_visa_agent") as v,
    ):
        f.return_value.run = AsyncMock(return_value=_FLIGHTS)
        h.return_value.run = AsyncMock(return_value=_HOTELS)
        w.return_value.run = AsyncMock(return_value=_WEATHER)
        v.return_value.run = AsyncMock(return_value=_VISA)
        yield {"flights": f, "hotels": h, "weather": w, "visa": v}
    get_cache().clear()


def _post(client, admin_headers, **overrides):
    return client.post(
        "/api/compare/destination",
        json={**_PAYLOAD, **overrides},
        headers=admin_headers,
    )


def test_requires_auth(client):
    r = client.post("/api/compare/destination", json=_PAYLOAD)
    assert r.status_code in (401, 403)


def test_happy_path(client, admin_headers, agents):
    r = _post(client, admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["flight"]["price_usd"] == 900
    assert body["hotel"]["typical_nightly_usd"] == 120
    assert body["weather"]["total_days"] == 1
    assert body["missing"] == []
    assert body["ease"]["total"] is not None


def test_static_visa_skips_visa_agent(client, admin_headers, agents):
    with patch(
        "app.api.routes.compare.get_static_visa",
        return_value={"requirement": {"visa_type": "visa-free", "max_stay_days": 90}},
    ):
        r = _post(client, admin_headers)
    assert r.status_code == 200
    assert r.json()["visa"]["verified"] is True
    agents["visa"].return_value.run.assert_not_called()


def test_ai_visa_used_when_not_static(client, admin_headers, agents):
    r = _post(client, admin_headers, destination="Zzyzx Nowhere")
    assert r.status_code == 200
    assert r.json()["visa"] == {
        "visa_type": "e-visa",
        "max_stay_days": 30,
        "fee_usd": 50,
        "processing_time": None,
        "verified": False,
    }
    agents["visa"].return_value.run.assert_called_once()


def test_one_agent_failing_is_partial(client, admin_headers, agents):
    agents["hotels"].return_value.run = AsyncMock(side_effect=RuntimeError("boom"))
    r = _post(client, admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["hotel"] is None and "hotels" in body["missing"]
    assert body["flight"]["price_usd"] == 900


def test_agent_error_result_counts_as_failure(client, admin_headers, agents):
    agents["flights"].return_value.run = AsyncMock(return_value={"error": "nope"})
    r = _post(client, admin_headers)
    assert r.status_code == 200 and "flights" in r.json()["missing"]


def test_timeout_is_partial_and_cancels_agent(client, admin_headers, agents):
    cancelled = []

    async def slow(request):
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    agents["weather"].return_value.run = slow
    with patch("app.api.routes.compare._WEATHER_TIMEOUT", 0.01):
        r = _post(client, admin_headers)
    assert r.status_code == 200 and "weather" in r.json()["missing"]
    assert cancelled == [True]


def test_all_failing_is_502_and_not_cached(client, admin_headers, agents):
    for name in ("flights", "hotels", "weather", "visa"):
        agents[name].return_value.run = AsyncMock(side_effect=RuntimeError("x"))
    with patch("app.api.routes.compare.get_static_visa", return_value=None):
        assert _post(client, admin_headers).status_code == 502
        # Recovery on the next call proves the failure wasn't cached.
        agents["flights"].return_value.run = AsyncMock(return_value=_FLIGHTS)
        assert _post(client, admin_headers).status_code == 200


def test_multi_city_rejected(client, admin_headers, agents):
    r = _post(client, admin_headers, destinations=["Paris", "Rome", "Tokyo"])
    assert r.status_code == 422
    assert "single destinations" in r.text
    agents["flights"].return_value.run.assert_not_called()


def test_second_identical_call_served_from_cache(client, admin_headers, agents):
    first = _post(client, admin_headers)
    second = _post(client, admin_headers)
    assert first.json() == second.json()
    agents["flights"].return_value.run.assert_called_once()
    agents["hotels"].return_value.run.assert_called_once()


def test_partial_result_not_cached(client, admin_headers, agents):
    agents["hotels"].return_value.run = AsyncMock(side_effect=RuntimeError("boom"))
    assert "hotels" in _post(client, admin_headers).json()["missing"]
    agents["hotels"].return_value.run = AsyncMock(return_value=_HOTELS)
    second = _post(client, admin_headers).json()
    assert second["missing"] == [] and second["hotel"] is not None


def test_factory_failure_leaves_no_unawaited_coroutines(client, admin_headers, agents):
    import warnings

    agents["weather"].side_effect = RuntimeError("ctor failed")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(RuntimeError):
            _post(client, admin_headers, destination="Zzyzx Nowhere")
        import gc

        gc.collect()
    assert not [w for w in caught if "never awaited" in str(w.message)]
