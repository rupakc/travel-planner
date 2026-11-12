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
    assert sp.scrub_selections(SEL, "exact", show_origin=True) == SEL
    sp.scrub_selections(SEL, "hidden")
    assert SEL["hotel"]["check_in"] == "2026-04-01"


def test_sanitize_plan_applies_scrub():
    plan = {**PLAN, "selections": SEL}
    assert "2026-04-01" not in _flat(sp.sanitize_plan(plan, {}, None)["selections"])
    ex = sp.sanitize_plan(plan, {"dates": "exact"}, None)["selections"]
    assert ex["hotel"]["check_in"] == "2026-04-01"


FLIGHT_SEL = {
    "flight": {
        "airline": "ANA",
        "price_usd": 900,
        "origin": "New York, USA",
        "outbound": {
            "airline": "ANA",
            "origin": "JFK",
            "destination": "NRT",
            "departure_time": "2026-05-01T10:00",
            "duration_minutes": 840,
        },
        "return": {"origin": "NRT", "destination": "JFK", "airline": "ANA"},
        "booking_url": "https://www.google.com/travel/flights#flt=JFK.NRT.2026-05-01*NRT.JFK.2026-05-08",
        "leg_from": "New York",
    },
    "hotel": {
        "name": "H",
        "booking_url": "https://h.example/x?checkin=2026-05-01&checkout=2026-05-08",
        "info_url": "https://h.example/about",
        "note": "Stay 2026-05-01 to 2026-05-08",
    },
    "itinerary": {
        "days": [
            {
                "day": 1,
                "slots": [
                    {
                        "time_of_day": "morning",
                        "title": "T",
                        "duration": "2h",
                        "duration_minutes": 120,
                        "notes": "private",
                    }
                ],
            }
        ]
    },
    "itinerary_notes": {"1": "x"},
    "itinerary_edits": {"1": {}},
}


def test_urls_with_dates_dropped_hidden_and_month():
    for mode in ("hidden", "month"):
        out = sp.scrub_selections(FLIGHT_SEL, mode, show_origin=True)
        flat = _flat(out)
        assert "2026-05-0" not in flat and "checkin" not in flat and "flt=" not in flat
        assert out["hotel"]["info_url"] == "https://h.example/about"
    m = sp.scrub_selections(FLIGHT_SEL, "month", show_origin=True)
    assert m["hotel"]["note"] == "Stay 2026-05 to 2026-05"
    assert "note" not in sp.scrub_selections(FLIGHT_SEL, "hidden")["hotel"]


def test_origin_scrubbed_in_every_mode():
    for mode in ("hidden", "month", "exact"):
        out = sp.scrub_selections(
            FLIGHT_SEL, mode, show_origin=False, origin="New York, USA"
        )
        f = out["flight"]
        assert "origin" not in f and "leg_from" not in f
        assert "origin" not in f["outbound"]
        assert "destination" not in f["return"]
        assert "booking_url" not in f
    ex = sp.scrub_selections(FLIGHT_SEL, "exact", show_origin=False)
    assert ex["flight"]["outbound"]["departure_time"] == "2026-05-01T10:00"
    assert "booking_url" in ex["hotel"]


def test_private_notes_and_time_of_day():
    for mode in ("hidden", "month", "exact"):
        out = sp.scrub_selections(FLIGHT_SEL, mode)
        assert "itinerary_notes" not in out and "itinerary_edits" not in out
        slot = out["itinerary"]["days"][0]["slots"][0]
        assert slot["time_of_day"] == "morning" and slot["duration"] == "2h"
        assert slot["duration_minutes"] == 120 and "notes" not in slot


def test_card_wrap_linear_and_clipped():
    import time

    from app.services import share_card

    t = time.time()
    snap = sp.build_snapshot("plan", {}, plan={"name": "x" * 5000, "search_data": {}})
    assert len(snap["headline"]) <= 120
    share_card.render({"headline": "ab " * 3000, "kind": "plan"})
    share_card.render({"headline": "w" * 5000, "kind": "plan"})
    assert time.time() - t < 1


def test_plural_stat_labels():
    from app.services.share_card import stat_text

    assert stat_text({"key": "activities", "count": 1}) == "1 activity"
    assert stat_text({"key": "hotels", "count": 1}) == "1 hotel"
    assert stat_text({"key": "hotels", "count": 2}) == "2 hotels"
    s = sp.build_snapshot(
        "savings", {}, savings={"total_usd": 5, "drops_caught": 0, "targets_hit": 2}
    )
    assert s["stats"] == [{"key": "targets_hit", "count": 2}]


def test_ipv6_clients_share_a_64_bucket():
    from types import SimpleNamespace

    from app.core.rate_limit import caller_key

    def req(h):
        return SimpleNamespace(client=SimpleNamespace(host=h))

    assert caller_key(req("2001:db8:1:2::1"), None) == caller_key(
        req("2001:db8:1:2:ffff::9"), None
    )
    assert caller_key(req("1.2.3.4"), None) == "ip:1.2.3.4"
