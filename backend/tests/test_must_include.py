"""must_include / import_source through the search pipeline."""

from datetime import date
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.agents.activities_agent import ActivitiesAgent
from app.agents.itinerary_agent import ItineraryAgent
from app.agents.orchestrator import TravelOrchestrator
from app.core.config import settings
from app.schemas.request import TravelSearchRequest
from app.services.must_include import ensure_must_include, merge_into_activities

BASE = {
    "origin": "London",
    "destination": "Lisbon, Portugal",
    "departure_date": "2026-12-01",
    "return_date": "2026-12-04",
    "nationality": "British",
}

MUST = [
    {
        "name": "Time Out Market",
        "kind": "food",
        "city": "Lisbon",
        "note": "Lunch under one roof",
        "quote": "start at Time Out Market",
        "lat": 38.707,
        "lng": -9.146,
        "verified": True,
    },
    {"name": "Belém Tower", "kind": "sight", "city": "Lisbon"},
    {"name": "Pena Palace", "kind": "sight", "city": "Lisbon", "town": "Sintra"},
]


def _req(**kw) -> TravelSearchRequest:
    return TravelSearchRequest(**{**BASE, **kw})


# ── Request schema ───────────────────────────────────────────────────────


def test_request_accepts_must_include_and_import_source():
    req = _req(
        must_include=MUST,
        import_source={
            "url": "https://wander.example/lisbon",
            "title": "48h in Lisbon",
        },
    )
    assert [p.name for p in req.must_include] == [
        "Time Out Market",
        "Belém Tower",
        "Pena Palace",
    ]
    assert req.must_include[2].town == "Sintra"
    assert req.import_source.title == "48h in Lisbon"
    dumped = req.model_dump(mode="json")  # part of the search cache key
    assert dumped["must_include"][0]["name"] == "Time Out Market"


def test_must_include_is_capped_at_25():
    with pytest.raises(ValidationError):
        _req(must_include=[{"name": f"P{i}", "city": "Lisbon"} for i in range(26)])


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd"])
def test_import_source_url_must_be_web(url):
    with pytest.raises(ValidationError):
        _req(import_source={"url": url, "title": "x"})


def test_defaults_are_none():
    req = _req()
    assert req.must_include is None and req.import_source is None


# ── Activities merge ─────────────────────────────────────────────────────


def test_link_places_lead_activities_and_dedupe_agent_copies():
    req = _req(must_include=MUST, import_source={"title": "48h in Lisbon"})
    agent_result = {
        "results": [
            {"name": "Jerónimos Monastery", "similarity_score": 0.9},
            {"name": "Torre de Belém", "similarity_score": 0.8},
            {
                "name": "Belém Tower Tour",
                "similarity_score": 0.7,
                "rating": 4.7,
                "price_usd": 12,
                "booking_url": "https://gyg.example/belem",
            },
        ]
    }
    merged = merge_into_activities(agent_result, req)
    names = [a["name"] for a in merged["results"]]
    assert names[:3] == ["Time Out Market", "Belém Tower", "Pena Palace"]
    assert "Belém Tower Tour" not in names  # folded into the link's item
    assert "Jerónimos Monastery" in names and "Torre de Belém" in names
    tom, belem, pena = merged["results"][:3]
    for item in (tom, belem, pena):
        assert item["source"] == "your_link" and item["from_link"] is True
        assert "link_verified" not in item  # never claims a checked URL
    assert tom["link_quote"] == "start at Time Out Market"
    assert tom["verification_note"] == "Located on Google Maps"
    assert belem["verification_note"] == "From your link — not independently checked"
    assert belem["rating"] == 4.7 and belem["price_usd"] == 12
    assert belem["booking_url"] == "https://gyg.example/belem"
    assert tom["lat"] == 38.707 and tom["category"] == "food"
    assert pena["location"] == "Sintra" and pena["city"] == "Lisbon"
    assert tom["booking_url"].startswith("https://www.google.com/maps/search/")


def test_link_places_survive_an_activities_error():
    merged = merge_into_activities({"error": "overloaded"}, _req(must_include=MUST))
    assert "error" not in merged
    assert [a["name"] for a in merged["results"]] == [p["name"] for p in MUST]


def test_no_must_include_leaves_result_alone():
    result = {"results": [{"name": "A"}]}
    assert merge_into_activities(result, _req()) is result


async def test_activities_agent_merges_link_places(monkeypatch):
    agent = ActivitiesAgent(settings.agents_dir)
    agent.execute = AsyncMock(return_value={"results": [{"name": "Oceanário"}]})
    out = await agent.run(_req(must_include=MUST))
    assert [a["name"] for a in out["results"]][:3] == [p["name"] for p in MUST]
    assert out["results"][3]["name"] == "Oceanário"


# ── Itinerary: prompt + deterministic post-check ─────────────────────────


def _slot(tod, activity, **kw):
    return {"time_of_day": tod, "activity": activity, "duration_hours": 2, **kw}


def _day(n, slots, city=None):
    day = {"day_number": n, "date": f"2026-12-0{n}", "slots": slots}
    if city:
        day["city"] = city
    return day


def _itinerary():
    return {
        "days": [
            _day(
                1,
                [
                    _slot("morning", "Arrive in Lisbon, transfer to hotel"),
                    _slot("afternoon", "Check in and rest"),
                    _slot("evening", "Dinner in Bairro Alto"),
                ],
            ),
            _day(
                2,
                [
                    _slot("morning", "Visit the Belém Tower and Jerónimos"),
                    _slot("afternoon", "Free time — explore at your own pace"),
                    _slot("evening", "Fado show in Alfama"),
                ],
            ),
            _day(
                3,
                [
                    _slot("morning", "Gulbenkian Museum"),
                    _slot("afternoon", "Shopping on Rua Augusta"),
                    _slot("evening", "Sunset at a miradouro"),
                ],
            ),
            _day(
                4,
                [
                    _slot("morning", "Final breakfast"),
                    _slot("afternoon", "Check out, head to the airport"),
                    _slot("evening", "Departure flight"),
                ],
            ),
        ]
    }


def _all_slots(itin):
    return [s for d in itin["days"] for s in d["slots"]]


def test_post_check_marks_scheduled_and_inserts_missing():
    req = _req(must_include=MUST)
    itin = ensure_must_include(_itinerary(), req)
    slots = _all_slots(itin)
    linked = {s["link_place"]: s for s in slots if s.get("from_link")}
    assert set(linked) == {"Time Out Market", "Belém Tower", "Pena Palace"}
    # already planned by the agent: kept, just marked
    assert linked["Belém Tower"]["activity"] == "Visit the Belém Tower and Jerónimos"
    # missing ones land in replaceable slots, never in arrival/departure logistics
    for name in ("Time Out Market", "Pena Palace"):
        assert name in linked[name]["activity"]
    days_with = {
        d["day_number"] for d in itin["days"] for s in d["slots"] if s.get("from_link")
    }
    assert days_with <= {2, 3}
    assert linked["Time Out Market"]["link_quote"] == "start at Time Out Market"
    assert linked["Time Out Market"]["lat"] == 38.707
    assert "Sintra" in linked["Pena Palace"]["location"]
    # free time goes first
    assert "Free time" not in " ".join(s["activity"] for s in itin["days"][1]["slots"])
    cov = itin["link_coverage"]
    assert cov["total"] == 3 and cov["missing"] == [] and cov["extras"] == []
    assert sorted(cov["scheduled"]) == sorted(p["name"] for p in MUST)


def test_post_check_puts_food_in_meal_times():
    req = _req(
        must_include=[{"name": "Cervejaria Ramiro", "kind": "food", "city": "Lisbon"}]
    )
    itin = ensure_must_include(_itinerary(), req)
    slot = next(s for s in _all_slots(itin) if s.get("from_link"))
    assert slot["time_of_day"] in ("afternoon", "evening")


def test_post_check_respects_multi_city_days():
    req = _req(
        destination="Porto, Portugal",
        destinations=["Lisbon, Portugal", "Porto, Portugal"],
        must_include=[{"name": "Livraria Lello", "kind": "sight", "city": "Porto"}],
    )
    itin = {
        "days": [
            _day(
                1,
                [
                    _slot("morning", "Arrive Lisbon"),
                    _slot("afternoon", "Alfama walk"),
                    _slot("evening", "Fado"),
                ],
                city="Lisbon",
            ),
            _day(
                2,
                [
                    _slot("morning", "Free morning"),
                    _slot("afternoon", "Belém"),
                    _slot("evening", "Dinner"),
                ],
                city="Lisbon",
            ),
            _day(
                3,
                [
                    _slot("morning", "Travel from Lisbon to Porto"),
                    _slot("afternoon", "Ribeira stroll"),
                    _slot("evening", "Port tasting"),
                ],
                city="Porto",
            ),
            _day(
                4,
                [
                    _slot("morning", "Breakfast"),
                    _slot("afternoon", "Airport"),
                    _slot("evening", "Departure flight"),
                ],
                city="Porto",
            ),
        ]
    }
    out = ensure_must_include(itin, req)
    day = next(d for d in out["days"] if any(s.get("from_link") for s in d["slots"]))
    assert day["city"] == "Porto"


def test_post_check_falls_back_to_day_notes_when_every_slot_is_taken():
    places = [
        {"name": f"Spot {i}", "kind": "sight", "city": "Lisbon"} for i in range(20)
    ]
    itin = ensure_must_include(_itinerary(), _req(must_include=places))
    cov = itin["link_coverage"]
    assert cov["total"] == 20
    assert len(cov["scheduled"]) + len(cov["extras"]) == 20
    assert cov["extras"], "some places must spill into day notes"
    noted = [n for d in itin["days"] for n in d.get("link_extras", [])]
    assert {n["name"] for n in noted} == set(cov["extras"])
    # arrival / departure logistics are never replaced
    assert itin["days"][0]["slots"][0]["activity"].startswith("Arrive")
    assert itin["days"][-1]["slots"][2]["activity"] == "Departure flight"


def test_post_check_without_must_include_is_a_no_op():
    itin = _itinerary()
    assert ensure_must_include(itin, _req()) == _itinerary()


async def test_itinerary_agent_prompt_lists_must_include_and_post_checks():
    agent = ItineraryAgent(settings.agents_dir)
    seen = {}

    async def fake_execute(prompt):
        seen["prompt"] = prompt
        return _itinerary()

    agent.execute = fake_execute
    req = _req(must_include=MUST)
    acts = merge_into_activities({"results": []}, req)
    out = await agent.run(req, activities=acts, hotels={"results": []})
    prompt = seen["prompt"]
    assert "MUST schedule every one" in prompt
    for p in MUST:
        assert p["name"] in prompt
    assert "Sintra" in prompt
    assert out["link_coverage"]["missing"] == []


async def test_itinerary_agent_error_is_left_for_the_fallback():
    agent = ItineraryAgent(settings.agents_dir)
    agent.execute = AsyncMock(return_value={"error": "boom"})
    out = await agent.run(_req(must_include=MUST), activities={}, hotels={})
    assert out == {"error": "boom"}


def test_template_fallback_includes_every_link_place():
    orch = TravelOrchestrator(settings.agents_dir)
    req = _req(
        must_include=MUST,
        departure_date=date(2026, 12, 1),
        return_date=date(2026, 12, 3),  # short trip: 1 sightseeing day
    )
    acts = merge_into_activities({"results": []}, req)
    itin = orch._build_fallback_itinerary(req, acts, {"results": []})
    cov = itin["link_coverage"]
    assert cov["missing"] == []
    assert len(cov["scheduled"]) + len(cov["extras"]) == 3
