"""Sections must never silently vanish — fallback packing list and
multi-city static transport coverage."""

from app.agents.orchestrator import TravelOrchestrator
from app.agents.static_results import get_static_getting_around
from app.schemas.request import TravelSearchRequest

BASE = {
    "origin": "New York, USA",
    "destination": "Paris, France",
    "departure_date": "2026-09-01",
    "return_date": "2026-09-10",
    "nationality": "American",
}


class TestFallbackPackingList:
    def test_matches_agent_schema(self):
        req = TravelSearchRequest(**BASE)
        result = TravelOrchestrator._build_fallback_packing_list(req)
        names = [c["name"] for c in result["categories"]]
        assert names == [
            "Documents",
            "Clothing",
            "Electronics",
            "Medications & Health",
            "Activity Gear",
            "Destination-Specific",
        ]
        for cat in result["categories"]:
            assert cat["items"], f"category {cat['name']} is empty"
            for it in cat["items"]:
                assert set(it) == {"item", "essential", "note"}
        assert result["total_items"] == sum(
            len(c["items"]) for c in result["categories"]
        )
        assert result["luggage_note"]

    def test_interests_add_gear(self):
        req = TravelSearchRequest(**BASE, interests=["hiking", "beach"])
        result = TravelOrchestrator._build_fallback_packing_list(req)
        gear = next(c for c in result["categories"] if c["name"] == "Activity Gear")
        items = [i["item"] for i in gear["items"]]
        assert "Swimwear" in items
        assert "Hiking layers" in items


class TestStaticGettingAroundMultiCity:
    def test_multi_city_covers_and_tags_every_stop(self):
        req = TravelSearchRequest(
            **BASE,
            destinations=["Paris, France", "Rome, Italy", "Barcelona, Spain"],
        )
        result = get_static_getting_around(req)
        tagged_cities = {o.get("city") for o in result["options"] if o.get("city")}
        assert {"Paris", "Rome", "Barcelona"} <= tagged_cities

    def test_single_city_options_are_untagged(self):
        req = TravelSearchRequest(**BASE)
        result = get_static_getting_around(req)
        assert result["options"]
        assert all("city" not in o for o in result["options"])

    def test_lookup_table_is_not_mutated(self):
        from app.agents.static_results import _GETTING_AROUND_TABLE

        req = TravelSearchRequest(**BASE, destinations=["Paris, France", "Rome, Italy"])
        get_static_getting_around(req)
        for opts in _GETTING_AROUND_TABLE.values():
            assert all("city" not in o for o in opts)
