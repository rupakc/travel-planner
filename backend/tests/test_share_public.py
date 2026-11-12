"""Pure snapshot service for share links."""

from app.services import share_public as sp

PLAN = {
    "name": "Lisbon <script>alert(1)</script>",
    "created_at": "c",
    "updated_at": "u",
    "search_data": {
        "origin": "NYC",
        "destination": "Lisbon",
        "departure_date": "2026-04-01",
        "return_date": "2026-04-07",
        "nationality": "American",
        "existing_visas": ["x"],
        "accessibility_needs": ["wheelchair"],
        "email": "a@b.c",
    },
    "selections": {
        "activities": [{"n": 1}, {"n": 2}],
        "hotel": {"name": "H"},
        "places_to_see": [{"n": 1}],
    },
}


def test_defaults_are_private():
    o = sp.normalize_options(None)
    assert o == {"dates": "hidden", "show_origin": False, "show_name": False}
    assert sp.normalize_options({"dates": "bogus", "show_name": "yes"})["dates"] == (
        "hidden"
    )
    assert sp.normalize_options({"show_name": "yes"})["show_name"] is False


def test_sanitize_hides_dates_origin_and_personal_fields():
    out = sp.sanitize_plan(PLAN, {}, None)
    s = out["search_data"]
    assert s == {"destination": "Lisbon"}
    assert "owner_name" not in out


def test_sanitize_month_and_exact():
    m = sp.sanitize_plan(PLAN, {"dates": "month"}, None)["search_data"]
    assert m["departure_date"] == "2026-04" and m["return_date"] == "2026-04"
    e = sp.sanitize_plan(PLAN, {"dates": "exact", "show_origin": True}, None)
    assert e["search_data"]["departure_date"] == "2026-04-01"
    assert e["search_data"]["origin"] == "NYC"
    assert "nationality" not in e["search_data"]


def test_snapshot_plan_headline_and_stats():
    snap = sp.build_snapshot("plan", {}, plan=PLAN)
    assert snap["headline"] == "7 days in Lisbon"
    assert snap["period"] is None and snap["origin"] is None
    assert snap["owner_name"] is None
    assert snap["stats"] == [
        {"key": "activities", "count": 2},
        {"key": "hotels", "count": 1},
        {"key": "places", "count": 1},
    ]


def test_snapshot_never_has_exact_dates_even_when_exact():
    snap = sp.build_snapshot("plan", {"dates": "exact"}, plan=PLAN)
    assert snap["period"] == "2026-04"
    assert "2026-04-01" not in repr(snap) and "2026-04-07" not in repr(snap)


def test_snapshot_name_only_with_show_name():
    assert (
        sp.build_snapshot("plan", {}, plan=PLAN, owner_name="Ann")["owner_name"] is None
    )
    snap = sp.build_snapshot("plan", {"show_name": True}, plan=PLAN, owner_name="Ann")
    assert snap["owner_name"] == "Ann"


def test_snapshot_recap_and_savings():
    r = sp.build_snapshot("recap", {}, plan=PLAN)
    assert r["headline"] == "My trip to Lisbon: recap"
    s = sp.build_snapshot(
        "savings", {}, savings={"total_usd": 120.0, "drops_caught": 3, "targets_hit": 1}
    )
    assert s["headline"] == "Caught drops worth $120"
    assert s["stats"][0] == {"key": "drops_caught", "count": 3}
    assert s["destination"] is None


def test_days_from_itinerary_when_no_dates():
    plan = {"name": "T", "search_data": {"destination": "Rome"},
            "selections": {"itinerary": {"days": [1, 2, 3]}}}  # fmt: skip
    assert sp.build_snapshot("plan", {}, plan=plan)["headline"] == "3 days in Rome"


def test_owner_display_name_rules():
    user = {"display_name": "  Ann ", "username": "ann99", "email": "ann@x.io"}
    assert sp.owner_display_name(user, {"show_name": False}) is None
    assert sp.owner_display_name(user, {"show_name": True}) == "Ann"
    assert sp.owner_display_name({"username": "bob"}, {"show_name": True}) == "bob"
    assert sp.owner_display_name({"username": "b@x.io"}, {"show_name": True}) is None


SEL = {
    "flight": {
        "airline": "TP",
        "departure_time": "2026-04-01T09:30:00",
        "arrival": "2026-04-01 17:05",
        "price_usd": 400,
        "legs": [{"departure_airport": "JFK", "at": "2026-04-01T09:30"}],
    },
    "hotel": {"name": "H", "check_in": "2026-04-01", "check_out": "2026-04-07", "stars": 4},
    "itinerary": {
        "days": [{"day": 1, "date": "2026-04-01", "slots": [{"time": "09:00", "title": "Tram"}]}]
    },
    "activities": [{"name": "Tram 28"}],
}  # fmt: skip


def _flat(obj):
    return repr(obj)


def test_scrub_hidden_removes_all_dates():
    out = sp.scrub_selections(SEL, "hidden")
    text = _flat(out)
    assert "2026" not in text and "09:00" not in text and "17:05" not in text
    assert out["flight"]["airline"] == "TP" and out["flight"]["price_usd"] == 400
    assert out["flight"]["legs"] == [{}]
    assert out["hotel"] == {"name": "H", "stars": 4}
    assert out["itinerary"]["days"][0]["day"] == 1
    assert out["activities"] == [{"name": "Tram 28"}]


def test_scrub_month_truncates_never_day_or_time():
    out = sp.scrub_selections(SEL, "month")
    assert out["hotel"]["check_in"] == "2026-04"
    assert out["flight"]["legs"][0]["at"] == "2026-04"
    assert out["itinerary"]["days"][0]["date"] == "2026-04"
    text = _flat(out)
    assert "2026-04-" not in text and "09:00" not in text and "T09" not in text


def test_scrub_exact_unchanged_and_input_not_mutated():
    assert sp.scrub_selections(SEL, "exact") is SEL
    sp.scrub_selections(SEL, "hidden")
    assert SEL["hotel"]["check_in"] == "2026-04-01"


def test_sanitize_plan_applies_scrub():
    plan = {**PLAN, "selections": SEL}
    assert "2026-04-01" not in _flat(sp.sanitize_plan(plan, {}, None)["selections"])
    ex = sp.sanitize_plan(plan, {"dates": "exact"}, None)["selections"]
    assert ex["hotel"]["check_in"] == "2026-04-01"
