"""
Tests for the five new backend services introduced with the 20-features update:
  - transit_estimator
  - location_scorer
  - smart_package
  - trip_health_scorer
  - weather_itinerary_adapter
"""

import pytest

from app.services.location_scorer import score_hotel_location
from app.services.smart_package import (
    _pick_activities,
    _pick_flight,
    _pick_hotel,
    _pick_sim,
    build_smart_package,
)
from app.services.transit_estimator import estimate_transit, haversine_km
from app.services.trip_health_scorer import compute_trip_health
from app.services.weather_itinerary_adapter import (
    _classify_slot,
    _get_clear_days,
    _get_poor_days,
    adapt_itinerary_for_weather,
)

# ──────────────────────────────────────────────────────────────────────────────
# transit_estimator
# ──────────────────────────────────────────────────────────────────────────────


class TestHaversineKm:
    def test_same_point_is_zero(self):
        assert haversine_km(35.6895, 139.6917, 35.6895, 139.6917) == pytest.approx(
            0.0, abs=0.001
        )

    def test_london_to_paris_approx(self):
        # Known great-circle distance ≈ 341 km
        km = haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
        assert 335 < km < 350

    def test_new_york_to_los_angeles(self):
        km = haversine_km(40.7128, -74.0060, 34.0522, -118.2437)
        assert 3900 < km < 4000

    def test_antipodal_points(self):
        km = haversine_km(0, 0, 0, 180)
        # Half circumference ≈ 20,015 km
        assert 19_900 < km < 20_200

    def test_north_south_symmetry(self):
        a = haversine_km(10.0, 0.0, -10.0, 0.0)
        b = haversine_km(-10.0, 0.0, 10.0, 0.0)
        assert a == pytest.approx(b, rel=1e-6)


class TestEstimateTransit:
    def test_walking_distance(self):
        # 0.3 km apart → walking
        result = estimate_transit(35.6895, 139.6917, 35.6922, 139.6917)
        assert result["mode"] == "walking"
        assert result["minutes"] < 15

    def test_metro_distance(self):
        # ~2.5 km apart → metro
        result = estimate_transit(35.6895, 139.6917, 35.7120, 139.6917)
        assert result["mode"] == "metro"
        assert "minutes" in result
        assert result["minutes"] > 0

    def test_taxi_distance(self):
        # ~7 km apart → taxi
        result = estimate_transit(35.6895, 139.6917, 35.7523, 139.6917)
        assert result["mode"] == "taxi"
        assert result["minutes"] > 5

    def test_car_distance(self):
        # ~25 km apart → car
        result = estimate_transit(35.6895, 139.6917, 35.9150, 139.6917)
        assert result["mode"] == "car"
        assert result["minutes"] > 0

    def test_result_shape(self):
        result = estimate_transit(35.6895, 139.6917, 35.7120, 139.7200)
        assert "minutes" in result
        assert "mode" in result
        assert "description" in result
        assert "distance_km" in result
        assert isinstance(result["minutes"], int)
        assert isinstance(result["distance_km"], float)

    def test_dense_city_slower_than_sparse(self):
        lat1, lon1, lat2, lon2 = 35.6895, 139.6917, 35.7200, 139.7000
        dense = estimate_transit(lat1, lon1, lat2, lon2, city_density="dense")
        sparse = estimate_transit(lat1, lon1, lat2, lon2, city_density="sparse")
        # Dense city should take longer (slower effective speed)
        assert dense["minutes"] >= sparse["minutes"]

    def test_description_contains_mode(self):
        result = estimate_transit(35.6895, 139.6917, 35.6922, 139.6917)
        assert result["mode"] in result["description"]

    def test_unknown_density_falls_back_to_medium(self):
        medium = estimate_transit(35.0, 139.0, 35.05, 139.0, city_density="medium")
        unknown = estimate_transit(35.0, 139.0, 35.05, 139.0, city_density="unknown")  # type: ignore[arg-type]
        assert medium["minutes"] == unknown["minutes"]


# ──────────────────────────────────────────────────────────────────────────────
# location_scorer
# ──────────────────────────────────────────────────────────────────────────────


class TestLocationScorer:
    def _hotel(self, lat=35.6895, lng=139.6917):
        return {"name": "Test Hotel", "lat": lat, "lng": lng}

    def _activity(self, name, lat, lng):
        return {"name": name, "lat": lat, "lng": lng}

    def test_hotel_without_coords_returns_zeros(self):
        result = score_hotel_location({}, [self._activity("X", 35.70, 139.70)])
        assert result["proximity_score"] == 0
        assert result["nearby_count"] == 0
        assert result["avg_minutes"] is None

    def test_empty_activities_returns_zeros(self):
        result = score_hotel_location(self._hotel(), [])
        assert result["proximity_score"] == 0
        assert result["nearby_count"] == 0

    def test_activities_without_coords_are_skipped(self):
        result = score_hotel_location(self._hotel(), [{"name": "No coords"}])
        assert result["proximity_score"] == 0

    def test_nearby_activity_scores_high(self):
        hotel = self._hotel(lat=35.6895, lng=139.6917)
        # 200 m away → walking → within 20-min threshold
        act = self._activity("Nearby Temple", lat=35.6913, lng=139.6917)
        result = score_hotel_location(hotel, [act])
        assert result["proximity_score"] > 50
        assert result["nearby_count"] >= 1

    def test_result_shape(self):
        hotel = self._hotel()
        acts = [
            self._activity(f"Act {i}", 35.6895 + i * 0.01, 139.6917) for i in range(5)
        ]
        result = score_hotel_location(hotel, acts)
        assert "proximity_score" in result
        assert "nearby_count" in result
        assert "avg_minutes" in result
        assert "nearest_activities" in result
        assert isinstance(result["nearest_activities"], list)

    def test_nearest_activities_sorted_by_distance(self):
        hotel = self._hotel(lat=35.6895, lng=139.6917)
        acts = [
            self._activity("Far", lat=35.80, lng=139.69),
            self._activity("Near", lat=35.6910, lng=139.6920),
        ]
        result = score_hotel_location(hotel, acts)
        if len(result["nearest_activities"]) >= 2:
            assert (
                result["nearest_activities"][0]["minutes"]
                <= result["nearest_activities"][1]["minutes"]
            )

    def test_latitude_field_alias(self):
        hotel = {"name": "Hotel", "latitude": 35.6895, "longitude": 139.6917}
        act = self._activity("Act", 35.6913, 139.6917)
        result = score_hotel_location(hotel, [act])
        assert result["proximity_score"] > 0

    def test_score_is_clamped_between_0_and_100(self):
        hotel = self._hotel()
        acts = [
            self._activity(f"A{i}", 35.6895 + i * 0.001, 139.6917) for i in range(10)
        ]
        result = score_hotel_location(hotel, acts)
        assert 0 <= result["proximity_score"] <= 100


# ──────────────────────────────────────────────────────────────────────────────
# smart_package
# ──────────────────────────────────────────────────────────────────────────────


SAMPLE_FLIGHTS = [
    {"airline": "ANA", "price_usd": 900, "stops": 0},
    {"airline": "JAL", "price_usd": 750, "stops": 1},
    {"airline": "Luxury Air", "price_usd": 2500, "stops": 0},
]

SAMPLE_HOTELS = [
    {
        "name": "Park Hyatt",
        "budget_tier": "luxury",
        "price_per_night_usd": 450,
        "rating": 4.8,
    },
    {
        "name": "APA Hotel",
        "budget_tier": "mid-range",
        "price_per_night_usd": 120,
        "rating": 4.3,
    },
    {
        "name": "Budget Inn",
        "budget_tier": "budget",
        "price_per_night_usd": 55,
        "rating": 3.5,
    },
]

SAMPLE_ACTIVITIES = [
    {"name": "Senso-ji", "price_usd": 0, "rating": 4.8},
    {"name": "TeamLab", "price_usd": 35, "rating": 4.7},
    {"name": "Mt. Fuji Tour", "price_usd": 120, "rating": 4.9},  # above $80 threshold
    {"name": "Shinjuku Walk", "price_usd": 0, "rating": 4.5},
]

SAMPLE_SIM = [
    {"provider": "IIJmio", "plan_name": "Basic", "price_usd": 15},
    {"provider": "Softbank", "plan_name": "Premium", "price_usd": 30},
]


class TestPickFlight:
    def test_picks_cheapest_eligible(self):
        flight = _pick_flight(SAMPLE_FLIGHTS)
        assert flight is not None
        assert flight["price_usd"] == 750  # cheapest with ≤1 stop

    def test_excludes_more_than_1_stop(self):
        flights = [{"price_usd": 100, "stops": 2}, {"price_usd": 200, "stops": 1}]
        flight = _pick_flight(flights)
        assert flight["price_usd"] == 200  # 2-stop excluded

    def test_returns_none_for_empty(self):
        assert _pick_flight([]) is None

    def test_returns_none_when_all_over_limit(self):
        flights = [{"price_usd": 100, "stops": 2}, {"price_usd": 200, "stops": 3}]
        assert _pick_flight(flights) is None


class TestPickHotel:
    def test_picks_mid_range(self):
        hotel = _pick_hotel(SAMPLE_HOTELS)
        assert hotel is not None
        assert "mid" in hotel["budget_tier"].lower()

    def test_picks_highest_rated_among_mid(self):
        hotels = [
            {"budget_tier": "mid-range", "rating": 3.5, "price_per_night_usd": 100},
            {"budget_tier": "mid-range", "rating": 4.5, "price_per_night_usd": 110},
        ]
        hotel = _pick_hotel(hotels)
        assert hotel["rating"] == 4.5

    def test_returns_none_when_no_mid_range(self):
        hotels = [{"budget_tier": "luxury"}, {"budget_tier": "budget"}]
        assert _pick_hotel(hotels) is None

    def test_returns_none_for_empty(self):
        assert _pick_hotel([]) is None


class TestPickActivities:
    def test_excludes_expensive(self):
        acts = _pick_activities(SAMPLE_ACTIVITIES)
        prices = [a["price_usd"] for a in acts]
        assert all(p < 80 for p in prices)

    def test_returns_max_count(self):
        acts = _pick_activities(SAMPLE_ACTIVITIES, max_count=2)
        assert len(acts) <= 2

    def test_sorts_by_rating(self):
        acts = _pick_activities(SAMPLE_ACTIVITIES)
        if len(acts) >= 2:
            assert acts[0].get("rating", 0) >= acts[1].get("rating", 0)


class TestPickSim:
    def test_picks_cheapest(self):
        sim = _pick_sim(SAMPLE_SIM)
        assert sim is not None
        assert sim["price_usd"] == 15

    def test_returns_none_for_empty(self):
        assert _pick_sim([]) is None


class TestBuildSmartPackage:
    def _sections(self):
        return {
            "flights": SAMPLE_FLIGHTS,
            "hotels": SAMPLE_HOTELS,
            "activities": SAMPLE_ACTIVITIES,
            "sim": SAMPLE_SIM,
        }

    def test_returns_empty_when_no_flights(self):
        sections = self._sections()
        sections["flights"] = []
        result = build_smart_package(sections, 3000, 2, 7)
        assert result == {}

    def test_returns_empty_when_no_mid_range_hotel(self):
        sections = self._sections()
        sections["hotels"] = [{"budget_tier": "luxury", "price_per_night_usd": 500}]
        result = build_smart_package(sections, 3000, 2, 7)
        assert result == {}

    def test_result_shape(self):
        result = build_smart_package(self._sections(), 3000, 2, 7)
        assert "flight" in result
        assert "hotel" in result
        assert "activities" in result
        assert "sim" in result
        assert "total_cost_usd" in result
        assert "savings_vs_expensive" in result

    def test_total_cost_is_positive(self):
        result = build_smart_package(self._sections(), 3000, 2, 7)
        assert result["total_cost_usd"] > 0

    def test_savings_non_negative(self):
        result = build_smart_package(self._sections(), 3000, 2, 7)
        assert result["savings_vs_expensive"] >= 0

    def test_activities_capped_at_three(self):
        result = build_smart_package(self._sections(), 3000, 2, 7)
        assert len(result["activities"]) <= 3

    def test_total_includes_hotel_nights(self):
        result_7 = build_smart_package(self._sections(), 5000, 1, 7)
        result_14 = build_smart_package(self._sections(), 5000, 1, 14)
        # More nights → higher cost
        assert result_14["total_cost_usd"] > result_7["total_cost_usd"]


# ──────────────────────────────────────────────────────────────────────────────
# trip_health_scorer
# ──────────────────────────────────────────────────────────────────────────────


class TestTripHealthScorer:
    def _complete_selections(self):
        return {
            "flight": {"airline": "ANA", "price_usd": 800},
            "hotel": {"name": "APA Hotel", "price_per_night_usd": 120},
            "activities": [{"name": f"Act {i}", "price_usd": 30} for i in range(14)],
            "sim": {"provider": "IIJmio", "price_usd": 15},
        }

    def _search_data(self, budget=3000, nights=7):
        return {"budget_usd": budget, "nights": nights, "num_travelers": 1}

    def test_result_shape(self):
        result = compute_trip_health(self._complete_selections(), self._search_data())
        assert "score" in result
        assert "grade" in result
        assert "factors" in result
        assert "warnings" in result

    def test_score_range(self):
        result = compute_trip_health(self._complete_selections(), self._search_data())
        assert 0 <= result["score"] <= 100

    def test_grade_a_for_excellent_plan(self):
        selections = {
            "flight": {"airline": "ANA", "price_usd": 500},
            "hotel": {"name": "APA", "price_per_night_usd": 100},
            "activities": [{"name": f"Act {i}", "price_usd": 20} for i in range(14)],
            "sim": {"provider": "IIJmio", "price_usd": 15},
        }
        result = compute_trip_health(
            selections, self._search_data(budget=5000, nights=7)
        )
        assert result["grade"] in ("A", "B")

    def test_empty_selections_returns_warnings(self):
        result = compute_trip_health({}, self._search_data())
        assert len(result["warnings"]) > 0

    def test_no_sim_adds_warning(self):
        sels = self._complete_selections()
        sels["sim"] = {}
        result = compute_trip_health(sels, self._search_data())
        warning_types = [w["type"] for w in result["warnings"]]
        assert "communication" in warning_types

    def test_over_budget_adds_warning(self):
        sels = {
            "flight": {"airline": "Lux", "price_usd": 3000},
            "hotel": {"name": "Ritz", "price_per_night_usd": 500},
            "activities": [],
            "sim": {"provider": "X", "price_usd": 10},
        }
        result = compute_trip_health(sels, self._search_data(budget=1000, nights=7))
        warning_types = [w["type"] for w in result["warnings"]]
        assert "budget" in warning_types

    def test_no_budget_set(self):
        result = compute_trip_health(
            self._complete_selections(), {"budget_usd": 0, "nights": 7}
        )
        # Should still return a result without crashing
        assert "score" in result

    def test_factors_list_has_expected_count(self):
        result = compute_trip_health(self._complete_selections(), self._search_data())
        assert (
            len(result["factors"]) == 5
        )  # Budget, Completeness, Communication, Pacing, Visa

    def test_sparse_activities_lowers_pacing_score(self):
        sels_sparse = {
            "flight": {"airline": "X", "price_usd": 500},
            "hotel": {"name": "Y", "price_per_night_usd": 100},
            "activities": [{"name": "One Activity", "price_usd": 0}],
            "sim": {"provider": "Z", "price_usd": 10},
        }
        sels_full = {
            "flight": {"airline": "X", "price_usd": 500},
            "hotel": {"name": "Y", "price_per_night_usd": 100},
            "activities": [{"name": f"Act {i}", "price_usd": 0} for i in range(14)],
            "sim": {"provider": "Z", "price_usd": 10},
        }
        result_sparse = compute_trip_health(sels_sparse, self._search_data(nights=7))
        result_full = compute_trip_health(sels_full, self._search_data(nights=7))
        pacing_sparse = next(
            f for f in result_sparse["factors"] if f["name"] == "Pacing"
        )
        pacing_full = next(f for f in result_full["factors"] if f["name"] == "Pacing")
        assert pacing_sparse["score"] < pacing_full["score"]

    def test_grades_cover_all_boundaries(self):
        """Verify _grade thresholds are exercised."""
        from app.services.trip_health_scorer import _grade

        assert _grade(95) == "A"
        assert _grade(80) == "B"
        assert _grade(65) == "C"
        assert _grade(50) == "D"
        assert _grade(30) == "F"


# ──────────────────────────────────────────────────────────────────────────────
# weather_itinerary_adapter
# ──────────────────────────────────────────────────────────────────────────────


def _make_weather(poor_dates=(), clear_dates=()):
    days = [{"date": d, "is_poor": True} for d in poor_dates]
    days += [{"date": d, "is_poor": False} for d in clear_dates]
    return {"days": days}


def _make_itinerary(days):
    """days: list of (date, slots) where slots: list of activity strings."""
    return {
        "days": [
            {
                "date": date,
                "slots": [{"activity": act, "location": ""} for act in slots],
            }
            for date, slots in days
        ]
    }


class TestClassifySlot:
    def test_outdoor_keyword(self):
        assert _classify_slot({"activity": "Morning hike to the mountain"}) == "outdoor"

    def test_indoor_keyword(self):
        assert _classify_slot({"activity": "Visit the National Museum"}) == "indoor"

    def test_unknown_returns_unknown(self):
        assert _classify_slot({"activity": "Free time"}) == "unknown"

    def test_mixed_leans_outdoor(self):
        # Both outdoor and indoor keyword → outdoor
        assert _classify_slot({"activity": "Beach restaurant lunch"}) == "outdoor"

    def test_checks_location_field(self):
        assert (
            _classify_slot({"activity": "Explore", "location": "Ueno Park"})
            == "outdoor"
        )


class TestGetPoorDays:
    def test_empty_weather(self):
        assert _get_poor_days({}) == set()

    def test_identifies_poor_days(self):
        weather = _make_weather(poor_dates=["2026-04-01", "2026-04-03"])
        assert _get_poor_days(weather) == {"2026-04-01", "2026-04-03"}

    def test_ignores_non_poor_days(self):
        weather = _make_weather(poor_dates=["2026-04-01"], clear_dates=["2026-04-02"])
        assert "2026-04-02" not in _get_poor_days(weather)


class TestGetClearDays:
    def test_identifies_clear_days(self):
        weather = _make_weather(poor_dates=["2026-04-01"], clear_dates=["2026-04-02"])
        assert "2026-04-02" in _get_clear_days(weather)
        assert "2026-04-01" not in _get_clear_days(weather)


class TestAdaptItineraryForWeather:
    def test_no_weather_returns_unchanged(self):
        itinerary = _make_itinerary([("2026-04-01", ["Museum visit"])])
        result = adapt_itinerary_for_weather(itinerary, {})
        assert result["weather_adapted"] is False
        assert result["weather_changes"] == []

    def test_no_poor_days_returns_unchanged(self):
        itinerary = _make_itinerary([("2026-04-01", ["Beach hike"])])
        weather = _make_weather(clear_dates=["2026-04-01"])
        result = adapt_itinerary_for_weather(itinerary, weather)
        assert result["weather_adapted"] is False

    def test_swaps_outdoor_on_rainy_day(self):
        itinerary = _make_itinerary(
            [
                ("2026-04-01", ["Morning hike", "Museum visit"]),
                ("2026-04-02", ["Gallery tour", "Temple walk"]),
            ]
        )
        weather = _make_weather(poor_dates=["2026-04-01"], clear_dates=["2026-04-02"])
        result = adapt_itinerary_for_weather(itinerary, weather)
        assert result["weather_adapted"] is True
        assert len(result["weather_changes"]) > 0

    def test_no_outdoor_on_poor_day_no_swap(self):
        itinerary = _make_itinerary(
            [
                ("2026-04-01", ["Museum visit", "Gallery tour"]),  # all indoor
                ("2026-04-02", ["Morning hike"]),
            ]
        )
        weather = _make_weather(poor_dates=["2026-04-01"], clear_dates=["2026-04-02"])
        result = adapt_itinerary_for_weather(itinerary, weather)
        # No outdoor slots on the poor day → no swaps
        assert result["weather_adapted"] is False

    def test_preserves_all_slots(self):
        itinerary = _make_itinerary(
            [
                ("2026-04-01", ["Beach surf", "Temple visit"]),
                ("2026-04-02", ["Museum tour", "Gallery walk"]),
            ]
        )
        weather = _make_weather(poor_dates=["2026-04-01"], clear_dates=["2026-04-02"])
        result = adapt_itinerary_for_weather(itinerary, weather)
        # Total slot count must be preserved
        original_count = sum(len(d["slots"]) for d in itinerary["days"])
        adapted_count = sum(len(d["slots"]) for d in result["days"])
        assert original_count == adapted_count

    def test_does_not_mutate_original(self):
        itinerary = _make_itinerary(
            [
                ("2026-04-01", ["Beach surf"]),
                ("2026-04-02", ["Museum tour"]),
            ]
        )
        original_day0_slot = itinerary["days"][0]["slots"][0]["activity"]
        weather = _make_weather(poor_dates=["2026-04-01"], clear_dates=["2026-04-02"])
        adapt_itinerary_for_weather(itinerary, weather)
        # Original must be untouched (deep-copy)
        assert itinerary["days"][0]["slots"][0]["activity"] == original_day0_slot

    def test_empty_itinerary_returns_gracefully(self):
        result = adapt_itinerary_for_weather(
            {}, _make_weather(poor_dates=["2026-04-01"])
        )
        assert result["weather_adapted"] is False

    def test_single_day_itinerary_no_crash(self):
        itinerary = _make_itinerary([("2026-04-01", ["Hiking trail"])])
        weather = _make_weather(poor_dates=["2026-04-01"])
        # Only one day — no clear day to swap with → should not crash
        result = adapt_itinerary_for_weather(itinerary, weather)
        assert "weather_adapted" in result
