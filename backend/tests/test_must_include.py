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


def test_post_check_ignores_model_set_flags_and_logistics_mentions():
    """Seen live: the model tagged every slot from_link, and an arrival slot
    whose hotel is "in Alfama" claimed the Alfama place."""
    itin = {
        "days": [
            _day(
                1,
                [
                    _slot(
                        "morning",
                        "Arrive in Lisbon, transfer to Memmo Alfama Hotel",
                        from_link=True,
                        location="Alfama",
                    ),
                    _slot("afternoon", "Explore Alfama neighbourhood", from_link=True),
                    _slot("evening", "Dinner", from_link=True),
                ],
            ),
            _day(
                2,
                [
                    _slot(
                        "morning",
                        "Embaixada Palace cultural tour",
                        location="Príncipe Real",
                        from_link=True,
                    ),
                    _slot("afternoon", "Príncipe Real neighbourhood walk"),
                    _slot("evening", "Santos & Cais do Sodré and the TimeOut Market"),
                ],
            ),
            _day(
                3,
                [
                    _slot("morning", "Breakfast"),
                    _slot("afternoon", "Airport"),
                    _slot("evening", "Departure flight"),
                ],
            ),
        ]
    }
    places = [
        {"name": "Alfama", "kind": "area", "city": "Lisbon"},
        {"name": "Principe Real", "kind": "area", "city": "Lisbon"},
        {"name": "Embaixada Palace", "kind": "sight", "city": "Lisbon"},
        {"name": "Santos & Cais do Sodre", "kind": "area", "city": "Lisbon"},
        {"name": "Timeout Market", "kind": "food", "city": "Lisbon"},
    ]
    out = ensure_must_include(itin, _req(must_include=places))
    slots = {
        (d["day_number"], s["time_of_day"]): s for d in out["days"] for s in d["slots"]
    }
    assert not slots[(1, "morning")].get("from_link")  # arrival logistics
    assert not slots[(1, "evening")].get("from_link")  # model's flag dropped
    assert slots[(1, "afternoon")]["link_place"] == "Alfama"
    assert slots[(2, "morning")]["link_place"] == "Embaixada Palace"
    assert slots[(2, "afternoon")]["link_place"] == "Principe Real"
    assert slots[(2, "evening")]["link_places"] == [
        "Santos & Cais do Sodre",
        "Timeout Market",
    ]
    cov = out["link_coverage"]
    assert sorted(cov["scheduled"]) == sorted(p["name"] for p in places)
    assert cov["extras"] == [] and cov["missing"] == []


# ── Review fixes: strict match (I-2), city check (I-3), logistics (I-4) ─────


def test_one_common_word_never_counts_as_the_place():
    req = _req(
        must_include=[
            {"name": "Sé Cathedral", "kind": "sight", "city": "Lisbon"},
            {"name": "Tram 28", "kind": "transport", "city": "Lisbon"},
            {"name": "LX Factory", "kind": "shopping", "city": "Lisbon"},
        ]
    )
    itin = {
        "days": [
            _day(
                1,
                [
                    _slot("morning", "Arrive in Lisbon"),
                    _slot("afternoon", "Take the tram to Belém"),
                ],
            ),
            _day(
                2,
                [
                    _slot("morning", "Visit the Jerónimos cathedral-like monastery"),
                    _slot("afternoon", "Lunch at a former factory canteen in Marvila"),
                    _slot("evening", "Fado dinner"),
                ],
            ),
            _day(
                3,
                [
                    _slot("morning", "Sintra palaces"),
                    _slot("afternoon", "Cascais beach"),
                    _slot("evening", "Free time"),
                ],
            ),
            _day(
                4,
                [
                    _slot("morning", "Pack and check out"),
                    _slot("afternoon", "Flight home"),
                ],
            ),
        ]
    }
    out = ensure_must_include(itin, req)
    texts = {
        s["link_place"]: s["activity"]
        for d in out["days"]
        for s in d["slots"]
        if s.get("from_link")
    }
    # every place is really in its slot's text now — none "found" in a lookalike
    for name, activity in texts.items():
        assert name in activity, (name, activity)
    assert set(texts) | set(out["link_coverage"]["extras"]) == {
        "Sé Cathedral",
        "Tram 28",
        "LX Factory",
    }


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("Sé Cathedral", "Lisbon Sé Cathedral at opening time"),
        ("Tram 28", "Ride Tram 28 through Graça"),
        ("LX Factory", "Brunch and shops at LX Factory"),
        ("Santos & Cais do Sodre", "Santos & Cais do Sodré neighbourhood"),
        ("Timeout Market", "Dinner at the TimeOut Market"),
        ("Principe Real", "Príncipe Real neighbourhood walk"),
    ],
)
def test_real_mentions_still_match(name, text):
    req = _req(must_include=[{"name": name, "kind": "sight", "city": "Lisbon"}])
    itin = {
        "days": [
            _day(1, [_slot("morning", "Arrive")]),
            _day(2, [_slot("afternoon", text)]),
            _day(3, [_slot("evening", "Departure flight")]),
        ]
    }
    out = ensure_must_include(itin, req)
    slot = out["days"][1]["slots"][0]
    assert slot["activity"] == text and slot["link_place"] == name


def test_a_mention_on_another_citys_day_does_not_count():
    req = _req(
        destination="Kyoto, Japan",
        destinations=["Tokyo, Japan", "Kyoto, Japan"],
        destination_nights=[2, None],
        must_include=[{"name": "Senso-ji", "kind": "sight", "city": "Tokyo"}],
    )
    itin = {
        "days": [
            _day(
                1,
                [
                    _slot("morning", "Arrive at Narita airport"),
                    _slot("afternoon", "Shibuya walk"),
                ],
                city="Tokyo",
            ),
            _day(
                2,
                [
                    _slot("morning", "Tsukiji market"),
                    _slot("afternoon", "Free time to explore"),
                ],
                city="Tokyo",
            ),
            _day(
                3,
                [
                    _slot("morning", "Shinkansen from Tokyo to Kyoto"),
                    _slot("afternoon", "Fushimi Inari"),
                    _slot("evening", "Senso-ji souvenirs at Gion"),
                ],
                city="Kyoto",
            ),
            _day(
                4,
                [
                    _slot("morning", "Kinkaku-ji"),
                    _slot("evening", "Depart for airport"),
                ],
                city="Kyoto",
            ),
        ]
    }
    out = ensure_must_include(itin, req)
    marked = [
        (d["city"], s["activity"])
        for d in out["days"]
        for s in d["slots"]
        if s.get("from_link")
    ]
    assert marked == [("Tokyo", "Senso-ji")]


@pytest.mark.parametrize(
    "activity",
    [
        "Alfa Pendular train Lisbon → Porto",
        "Shinkansen to Kyoto",
        "Train from Lisbon",
        "Check into your hotel in Porto",
        "Ferry across the Tagus",
        "Coach transfer to the old town",
        "Drive to Sintra",
        "Head to Porto",
    ],
)
def test_logistics_slots_are_never_replaced(activity):
    req = _req(
        must_include=[
            {"name": f"Spot {i}", "kind": "sight", "city": "Lisbon"} for i in range(9)
        ]
    )
    itin = {
        "days": [
            _day(
                1,
                [
                    _slot("morning", "Arrive"),
                    _slot("afternoon", "Lunch"),
                    _slot("evening", "Dinner"),
                ],
            ),
            _day(
                2,
                [
                    _slot(
                        "morning",
                        activity,
                        estimated_cost_usd=35,
                        booking_url="https://cp.pt",
                    ),
                    _slot("afternoon", "Museum"),
                    _slot("evening", "Bar"),
                ],
            ),
            _day(
                3,
                [
                    _slot("morning", "Breakfast"),
                    _slot("afternoon", "Market"),
                    _slot("evening", "Departure flight"),
                ],
            ),
        ]
    }
    out = ensure_must_include(itin, req)
    kept = out["days"][1]["slots"][0]
    assert kept["activity"] == activity and not kept.get("from_link")
    assert kept["booking_url"] == "https://cp.pt"


def test_inserted_slots_drop_the_old_cost_and_booking_link_and_skip_travel_in_days():
    req = _req(
        destination="Porto, Portugal",
        destinations=["Lisbon, Portugal", "Porto, Portugal"],
        destination_nights=[2, None],
        must_include=[{"name": "Livraria Lello", "kind": "shopping", "city": "Porto"}],
    )
    itin = {
        "days": [
            _day(
                1,
                [_slot("morning", "Arrive"), _slot("afternoon", "Alfama")],
                city="Lisbon",
            ),
            _day(
                2, [_slot("morning", "Belém"), _slot("afternoon", "LX")], city="Lisbon"
            ),
            _day(
                3,
                [
                    _slot(
                        "morning",
                        "Alfa Pendular train Lisbon → Porto",
                        estimated_cost_usd=35,
                        booking_url="https://cp.pt",
                    ),
                    _slot("afternoon", "Check into your hotel in Porto"),
                    _slot(
                        "evening",
                        "Port tasting in Gaia",
                        estimated_cost_usd=25,
                        booking_url="https://port.example",
                    ),
                ],
                city="Porto",
            ),
            _day(
                4,
                [
                    _slot(
                        "morning",
                        "Clérigos Tower",
                        estimated_cost_usd=8,
                        booking_url="https://clerigos.example",
                        start_time="09:30",
                    ),
                    _slot(
                        "afternoon",
                        "Clérigos Tower again",
                        estimated_cost_usd=8,
                        booking_url="https://clerigos.example",
                        start_time="13:30",
                    ),
                    _slot("evening", "Departure flight"),
                ],
                city="Porto",
            ),
            _day(
                5,
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
    day3 = out["days"][2]["slots"]
    assert [s["activity"] for s in day3][:2] == [
        "Alfa Pendular train Lisbon → Porto",
        "Check into your hotel in Porto",
    ]
    slot = next(s for d in out["days"] for s in d["slots"] if s.get("from_link"))
    assert slot["activity"].startswith("Livraria Lello")
    assert out["days"][3]["slots"].count(slot) == 1  # a non-travel day in Porto
    assert slot["estimated_cost_usd"] is None
    assert "booking_url" not in slot and "start_time" not in slot


def test_must_include_rejects_blank_names_unknown_kinds_and_duplicates():
    req = _req(
        must_include=[
            {"name": "  Belém Tower ", "kind": "SPACESHIP", "city": "Lisbon"},
            {"name": "belém tower", "city": "Lisbon"},
        ]
    )
    assert [(p.name, p.kind) for p in req.must_include] == [("Belém Tower", "sight")]
    with pytest.raises(ValidationError):
        _req(must_include=[{"name": "   ", "city": "Lisbon"}])


def test_post_check_is_idempotent_even_for_transport_places():
    req = _req(
        must_include=[
            {"name": "Tram 28", "kind": "transport", "city": "Lisbon"},
            {"name": "Sé Cathedral", "kind": "sight", "city": "Lisbon"},
        ]
    )
    once = ensure_must_include(_itinerary(), req)
    assert ensure_must_include(once, req) == once


# ── Fix round 2: ordered phrase match, logistics match-not-replace ───────

from app.services.must_include import _same_place  # noqa: E402


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("Tokyo Tower", "Tokyo Skytree — Japan's tallest tower, sunset views"),
        (
            "Lisbon Cathedral",
            "Walk Lisbon-style tiled cafés then visit a cathedral in Tokyo",
        ),
        (
            "Osaka Castle",
            "Day trip: Osaka street food, then the castle-town lanes of Kawagoe",
        ),
        ("Ark Hills", "Roppongi Park Hills rooftop"),
        ("Tower Tokyo", "Tokyo Tower at night"),  # order matters
    ],
)
def test_phrase_match_rejects_scattered_or_partial_words(name, text):
    assert _same_place(name, text) is False


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("Sé Cathedral", "Lisbon Sé Cathedral at opening time"),
        ("Tram 28", "Hop on Tram 28 from Martim Moniz"),
        ("LX Factory", "Brunch at LX Factory"),
        ("LX Factory", "Brunch at LXFactory"),
        ("Senso-ji", "Sensoji at dawn"),
        ("Sensoji", "Senso-ji at dawn"),
        ("Senso-ji", "Senso ji temple"),
        ("Time Out Market", "Dinner at the TimeOut Market"),
        ("Timeout Market", "Dinner at the Time Out Market"),
        ("Giolitti", "Gelato at Giolitti's"),
        ("Praça das Flores", "Praca Das Flores picnic"),
    ],
)
def test_phrase_match_accepts_spelling_variants(name, text):
    assert _same_place(name, text) is True


def _city_word_itinerary():
    return {
        "days": [
            _day(1, [_slot("morning", "Arrive at Haneda")]),
            _day(
                2,
                [
                    _slot(
                        "morning", "Tokyo Skytree — Japan's tallest tower, sunset views"
                    ),
                    _slot("afternoon", "Roppongi Park Hills rooftop"),
                    _slot("evening", "Dinner in Ebisu"),
                ],
            ),
            _day(
                3,
                [
                    _slot(
                        "morning",
                        "Day trip: Osaka street food, then the castle-town lanes of Kawagoe",
                    ),
                    _slot(
                        "afternoon",
                        "Walk Lisbon-style tiled cafés then visit a cathedral in Tokyo",
                    ),
                ],
            ),
            _day(4, [_slot("morning", "Depart from Haneda")]),
        ]
    }


def test_city_plus_noun_names_are_not_claimed_by_unrelated_slots():
    req = _req(
        destination="Tokyo, Japan",
        must_include=[
            {"name": n, "kind": "sight", "city": "Tokyo"}
            for n in ("Tokyo Tower", "Lisbon Cathedral", "Ark Hills", "Osaka Castle")
        ],
    )
    out = ensure_must_include(_city_word_itinerary(), req)
    for day in out["days"]:
        for slot in day["slots"]:
            if slot.get("from_link"):
                assert slot["link_place"] in slot["activity"]  # inserted, not "found"


def _logistics_name_itinerary():
    return {
        "days": [
            _day(1, [_slot("morning", "Arrive in Lisbon")]),
            _day(
                2,
                [
                    _slot(
                        "morning",
                        "Hop on Tram 28 from Martim Moniz, then head to the castle",
                    ),
                    _slot("afternoon", "Train to Sintra for Pena Palace"),
                    _slot("evening", "Ferry Building food hall lunch"),
                ],
            ),
            _day(
                3,
                [
                    _slot("morning", "Belém pastries"),
                    _slot("afternoon", "Alfama walk"),
                    _slot("evening", "Fado dinner"),
                ],
            ),
            _day(4, [_slot("morning", "Check out and fly home")]),
        ]
    }


def test_places_named_in_travel_slots_are_matched_not_reinserted():
    req = _req(
        must_include=[
            {"name": "Tram 28", "kind": "transport", "city": "Lisbon"},
            {
                "name": "Pena Palace",
                "kind": "sight",
                "city": "Lisbon",
                "town": "Sintra",
            },
            {"name": "Ferry Building", "kind": "food", "city": "Lisbon"},
        ]
    )
    out = ensure_must_include(_logistics_name_itinerary(), req)
    day2 = [s.get("link_place") for s in out["days"][1]["slots"]]
    assert day2 == ["Tram 28", "Pena Palace", "Ferry Building"]
    assert [s["activity"] for s in out["days"][2]["slots"]] == [
        "Belém pastries",
        "Alfama walk",
        "Fado dinner",
    ]
    assert out["link_coverage"]["scheduled"] == [
        "Tram 28",
        "Pena Palace",
        "Ferry Building",
    ]


def test_alfa_pendular_on_the_travel_day_is_matched_not_duplicated():
    req = _req(
        destination="Porto, Portugal",
        destinations=["Lisbon, Portugal", "Porto, Portugal"],
        destination_nights=[2, None],
        must_include=[{"name": "Alfa Pendular", "kind": "transport", "city": "Porto"}],
    )
    itin = {
        "days": [
            _day(
                1,
                [_slot("morning", "Arrive"), _slot("evening", "Dinner in Bairro Alto")],
                city="Lisbon",
            ),
            _day(
                2,
                [_slot("morning", "Belém"), _slot("afternoon", "LX Factory")],
                city="Lisbon",
            ),
            _day(
                3,
                [
                    _slot(
                        "morning",
                        "Travel on Alfa Pendular high-speed train from Lisbon to Porto",
                        estimated_cost_usd=35,
                    )
                ],
                city="Porto",
            ),
            _day(
                4,
                [_slot("morning", "Ribeira"), _slot("evening", "Departure flight")],
                city="Porto",
            ),
        ]
    }
    out = ensure_must_include(itin, req)
    marked = [
        (d["day_number"], s["activity"])
        for d in out["days"]
        for s in d["slots"]
        if s.get("from_link")
    ]
    assert marked == [
        (3, "Travel on Alfa Pendular high-speed train from Lisbon to Porto")
    ]
    assert out["days"][0]["slots"][1]["activity"] == "Dinner in Bairro Alto"


def test_arrival_and_hotel_slots_still_never_claim_a_place():
    req = _req(must_include=[{"name": "Alfama", "kind": "area", "city": "Lisbon"}])
    itin = {
        "days": [
            _day(
                1,
                [_slot("morning", "Arrive in Lisbon, transfer to Memmo Alfama Hotel")],
            ),
            _day(2, [_slot("morning", "Museum"), _slot("afternoon", "Free time")]),
            _day(3, [_slot("evening", "Departure flight")]),
        ]
    }
    out = ensure_must_include(itin, req)
    assert not out["days"][0]["slots"][0].get("from_link")
    assert out["days"][1]["slots"][1]["link_place"] == "Alfama"


def test_unmatched_transport_places_become_day_notes_never_slots():
    req = _req(
        must_include=[{"name": "Tram 28", "kind": "transport", "city": "Lisbon"}]
    )
    out = ensure_must_include(_itinerary(), req)
    assert not any(s.get("from_link") for d in out["days"] for s in d["slots"])
    notes = [
        (d["day_number"], x["name"])
        for d in out["days"]
        for x in d.get("link_extras", [])
    ]
    assert notes and notes[0][1] == "Tram 28" and notes[0][0] not in (1, 4)
    assert out["link_coverage"]["extras"] == ["Tram 28"]


@pytest.mark.parametrize(
    "activity",
    [
        "Lisbon – Porto on the Alfa Pendular (3h)",
        "Hikari bullet service, Tokyo ⇒ Kyoto",
        "Nozomi bullet, Tokyo - Kyoto",
    ],
)
def test_keywordless_transit_between_two_stops_is_protected(activity):
    stops = (
        ["Tokyo, Japan", "Kyoto, Japan"]
        if "Tokyo" in activity
        else ["Lisbon, Portugal", "Porto, Portugal"]
    )
    req = _req(
        destination=stops[-1],
        destinations=stops,
        must_include=[{"name": f"Spot {i}", "kind": "sight"} for i in range(6)],
    )
    itin = {
        "days": [
            _day(1, [_slot("morning", "Arrive")]),
            _day(
                2,
                [
                    _slot("morning", activity, estimated_cost_usd=95),
                    _slot("afternoon", "Market"),
                ],
            ),
            _day(3, [_slot("evening", "Departure flight")]),
        ]
    }
    out = ensure_must_include(itin, req)
    assert out["days"][1]["slots"][0]["activity"] == activity


def test_day_and_trip_totals_drop_the_replaced_activitys_cost():
    req = _req(
        must_include=[{"name": "Livraria Lello", "kind": "shopping", "city": "Lisbon"}]
    )
    itin = {
        "days": [
            _day(1, [_slot("morning", "Arrive")]),
            {
                **_day(
                    2,
                    [
                        _slot("morning", "Gulbenkian Museum", estimated_cost_usd=20),
                        _slot("afternoon", "Shopping", estimated_cost_usd=30),
                    ],
                ),
                "daily_estimated_cost_usd": 100,
            },
            _day(3, [_slot("evening", "Departure flight")]),
        ],
        "total_estimated_cost_usd": 300,
    }
    out = ensure_must_include(itin, req)
    replaced = next(s for s in out["days"][1]["slots"] if s.get("from_link"))
    old = 20 if replaced["time_of_day"] == "morning" else 30
    assert out["days"][1]["daily_estimated_cost_usd"] == 100 - old
    assert out["total_estimated_cost_usd"] == 300 - old
