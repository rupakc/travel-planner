"""Emergency card must cover EVERY stop of a multi-city trip — not just the
final destination — in both the static Phase-0 path and the AI agent prompt."""

from app.agents.emergency_card_agent import _same_country, build_emergency_prompt
from app.agents.static_results import get_static_emergency_card
from app.schemas.request import TravelSearchRequest

BASE = {
    "origin": "New York, USA",
    "destination": "Paris, France",
    "departure_date": "2026-09-01",
    "return_date": "2026-09-10",
    "nationality": "American",
}


class TestSameCountry:
    def test_plain_country_still_matches(self):
        assert _same_country("American", "USA")
        assert _same_country("Japanese", "Japan")

    def test_city_first_string_matches_by_country_part(self):
        assert _same_country("American", "San Francisco, USA")
        assert not _same_country("American", "Amsterdam, Netherlands")


class TestEmergencyPrompt:
    def test_single_city_prompt_unchanged(self):
        req = TravelSearchRequest(**BASE)
        prompt = build_emergency_prompt(req)
        assert "Destination: Paris, France" in prompt
        assert "MULTI-CITY" not in prompt

    def test_multi_city_prompt_lists_every_stop(self):
        req = TravelSearchRequest(
            **BASE,
            destinations=[
                "Berlin, Germany",
                "Amsterdam, Netherlands",
                "New York, USA",
                "San Francisco, USA",
            ],
        )
        prompt = build_emergency_prompt(req)
        assert "MULTI-CITY" in prompt
        for city in req.destinations:
            assert city in prompt
        assert "Do NOT skip any" in prompt

    def test_multi_city_prompt_flags_home_country_stops(self):
        req = TravelSearchRequest(
            **BASE,
            destinations=["Amsterdam, Netherlands", "San Francisco, USA"],
        )
        prompt = build_emergency_prompt(req)
        assert "Home-country cities" in prompt
        assert (
            "San Francisco, USA"
            in prompt.split("Home-country cities")[1].split("\n")[0]
        )


class TestStaticEmergencyCard:
    def test_multi_city_returns_entry_per_known_stop(self):
        req = TravelSearchRequest(
            **BASE,
            destinations=["Paris, France", "Tokyo, Japan", "New York, USA"],
        )
        result = get_static_emergency_card(req)
        assert result is not None and result["_static_only"]
        cities = result["cities"]
        assert [c["city"] for c in cities] == [
            "Paris, France",
            "Tokyo, Japan",
            "New York, USA",
        ]
        police = [c["emergency_numbers"]["police"] for c in cities]
        assert police == ["17", "110", "911"]

    def test_single_city_keeps_flat_schema(self):
        req = TravelSearchRequest(**BASE)
        result = get_static_emergency_card(req)
        assert result is not None
        assert "cities" not in result
        assert result["emergency_numbers"]["police"] == "17"
