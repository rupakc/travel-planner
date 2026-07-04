"""Tests for the Taste Graph — signal extraction, aggregation, and routes."""

from unittest.mock import AsyncMock, patch

from app.db.taste_db import (
    clear_taste_profile,
    derive_taste_context,
    extract_signals,
    get_taste_profile,
    hotel_tier_from_star_rating,
    record_signals,
)

SEARCH_DATA = {
    "origin": "New York, USA",
    "destination": "Tokyo, Japan",
    "departure_date": "2026-08-10",
    "return_date": "2026-08-17",
    "interests": ["food", "history"],
    "nationality": "American",
    "pace": "relaxed",
}

SELECTIONS = {
    "hotel": {"name": "Park Hyatt", "star_rating": 5.0},
    "flight": {"outbound": {"stops": 0}, "price_usd": 900},
    "activities": [
        {"name": "Sushi class", "category": "Food"},
        {"name": "Senso-ji", "category": "history"},
    ],
}


class TestHotelTier:
    def test_tiers_from_star_rating(self):
        assert hotel_tier_from_star_rating(5.0) == "luxury"
        assert hotel_tier_from_star_rating(4.0) == "premium"
        assert hotel_tier_from_star_rating(3.5) == "mid-range"
        assert hotel_tier_from_star_rating(2.0) == "budget"

    def test_invalid_rating_returns_none(self):
        assert hotel_tier_from_star_rating(None) is None
        assert hotel_tier_from_star_rating("five stars") is None


class TestExtractSignals:
    def test_extracts_all_signal_types(self):
        signals = extract_signals(SEARCH_DATA, SELECTIONS)
        assert ("interest", "food") in signals
        assert ("interest", "history") in signals
        assert ("destination", "Tokyo, Japan") in signals
        assert ("pace", "relaxed") in signals
        assert ("hotel_tier", "luxury") in signals
        assert ("flight_style", "non-stop") in signals
        assert ("activity_category", "food") in signals
        assert ("activity_category", "history") in signals

    def test_balanced_pace_is_not_a_signal(self):
        signals = extract_signals({**SEARCH_DATA, "pace": "balanced"}, {})
        assert not any(t == "pace" for t, _ in signals)

    def test_flight_with_stops(self):
        signals = extract_signals({}, {"flight": {"outbound": {"stops": 1}}})
        assert ("flight_style", "with stops (cheaper)") in signals

    def test_empty_and_malformed_inputs(self):
        assert extract_signals(None, None) == []
        assert extract_signals({}, {}) == []
        signals = extract_signals(
            {"interests": [None, "", "  "]},
            {
                "hotel": {"star_rating": "bad"},
                "flight": {"outbound": {"stops": "many"}},
                "activities": [None, {}, {"category": 3}],
            },
        )
        assert signals == []

    def test_legacy_selection_shapes_do_not_raise(self):
        # Older saved plans stored activities as plain strings and
        # flight/hotel as strings — extraction must not crash on them.
        signals = extract_signals(
            {"interests": "food"},
            {
                "hotel": "Park Hyatt",
                "flight": "AA100",
                "activities": ["Sushi class", "Senso-ji"],
            },
        )
        assert signals == []


class TestProfileAggregation:
    def test_record_aggregate_derive_and_clear(self, client):
        username = "taste-tester"
        clear_taste_profile(username)

        record_signals(
            username,
            extract_signals(SEARCH_DATA, SELECTIONS)
            + [("hotel_tier", "luxury"), ("activity_category", "food")],
        )

        profile = get_taste_profile(username)
        assert profile["total_signals"] > 0
        tiers = profile["signals"]["hotel_tier"]
        assert tiers[0]["value"] == "luxury"
        assert tiers[0]["count"] == 2
        categories = profile["signals"]["activity_category"]
        assert categories[0]["value"] == "food"

        context = derive_taste_context(username)
        assert "luxury hotels" in context
        assert "non-stop flights" in context
        assert "food" in context
        assert "relaxed-pace" in context

        deleted = clear_taste_profile(username)
        assert deleted > 0
        assert derive_taste_context(username) is None

    def test_unknown_user_has_no_context(self, client):
        assert derive_taste_context("never-seen-user") is None


class TestTasteRoutes:
    def test_requires_auth(self, client):
        assert client.get("/api/taste-profile").status_code in (401, 403)
        assert client.delete("/api/taste-profile").status_code in (401, 403)

    def test_profile_roundtrip_via_plans(self, client, admin_headers):
        client.delete("/api/taste-profile", headers=admin_headers)

        resp = client.post(
            "/api/plans",
            json={
                "name": "Tokyo trip",
                "search_data": SEARCH_DATA,
                "selections": SELECTIONS,
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        plan_id = resp.json()["id"]

        profile = client.get("/api/taste-profile", headers=admin_headers).json()
        assert profile["total_signals"] > 0
        assert "luxury hotels" in profile["context"]

        # Updating selections records additional signals
        resp = client.put(
            f"/api/plans/{plan_id}",
            json={"selections": SELECTIONS},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        updated = client.get("/api/taste-profile", headers=admin_headers).json()
        assert updated["total_signals"] > profile["total_signals"]

        resp = client.delete("/api/taste-profile", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["deleted_signals"] > 0
        cleared = client.get("/api/taste-profile", headers=admin_headers).json()
        assert cleared["total_signals"] == 0
        assert cleared["context"] is None

        client.delete(f"/api/plans/{plan_id}", headers=admin_headers)


class TestSearchInjection:
    def test_sync_search_injects_taste_context_for_authed_user(
        self, client, admin_headers
    ):
        client.delete("/api/taste-profile", headers=admin_headers)
        record_signals("admin", [("hotel_tier", "luxury")])

        captured = {}

        async def fake_run(request):
            captured["taste_context"] = request.taste_context
            return {"flights": {"results": []}}

        with patch("app.api.routes.search.get_orchestrator") as mock_get:
            mock_get.return_value.run = AsyncMock(side_effect=fake_run)
            resp = client.post(
                "/api/search/sync",
                json={**SEARCH_DATA, "taste_context": "client-injected nonsense"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        assert "luxury hotels" in captured["taste_context"]
        assert "nonsense" not in captured["taste_context"]
        clear_taste_profile("admin")

    def test_anonymous_search_has_no_taste_context(self, client):
        captured = {}

        async def fake_run(request):
            captured["taste_context"] = request.taste_context
            return {"flights": {"results": []}}

        with patch("app.api.routes.search.get_orchestrator") as mock_get:
            mock_get.return_value.run = AsyncMock(side_effect=fake_run)
            resp = client.post(
                "/api/search/sync",
                json={**SEARCH_DATA, "taste_context": "client-injected nonsense"},
            )
        assert resp.status_code == 200
        assert captured["taste_context"] is None
