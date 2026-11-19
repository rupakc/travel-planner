"""Trip carbon footprint: services/carbon.py and POST /api/carbon/trip.

Golden numbers are worked by hand from backend/app/data/carbon_factors.json
(DESNZ 2026, OWID) and the airports table, so a factor-table refresh that
changes a value fails here on purpose."""

import json
import math

import pytest

from app.core.config import settings
from app.services import carbon

TRIP = {
    "origin": "London",
    "destination": "Paris",
    "departure_date": "2026-05-01",
    "return_date": "2026-05-05",
    "num_travelers": 2,
}


def leg(o, d, **kw):
    return {"origin": o, "destination": d, "stops": 0, "layovers": [], **kw}


def lines(out, kind=None, category=None):
    return [
        ln
        for ln in out["lines"]
        if (kind is None or ln["kind"] == kind)
        and (category is None or ln["category"] == category)
    ]


def codes(out):
    return {a["code"] for a in out["assumptions"]}


# ── Factor table ─────────────────────────────────────────────────────────────


def test_every_factor_has_value_unit_source_year():
    f = carbon.factors()
    groups = [f["flight"], f["ground"], f["hotel"]["by_country"], f["food"]["products"]]
    groups.append({"hotel_default": f["hotel"]["default"]})
    for group in groups:
        for key, v in group.items():
            assert isinstance(v["value"], (int, float)) and v["value"] >= 0, key
            assert v["unit"].startswith("kg CO2e per "), key
            assert v["source"] in f["sources"], key
            assert isinstance(v["year"], int), key
    assert f["sources"]["desnz_2026"]["attribution"] == (
        "Contains public sector information licensed under the Open Government "
        "Licence v3.0"
    )
    assert f["sources"]["owid_food"]["licence"] == "CC BY 4.0"
    # Published values, spot-checked against the DESNZ 2026 flat file / OWID CSV
    assert f["flight"]["long_haul.economy"]["value"] == 0.11704
    assert f["flight"]["long_haul.economy"]["factor_id"] == "21_316_3170_11_1"
    assert f["ground"]["rail_national"]["value"] == 0.03092
    assert f["hotel"]["by_country"]["FR"]["value"] == 6.7
    assert f["food"]["products"]["beef_herd"]["value"] == 99.48


def test_diet_baskets_rank_as_expected():
    d = carbon.factors()["food"]["diets"]
    kg = {k: v["kg_per_day"] for k, v in d.items()}
    assert (
        kg["vegan"]
        < kg["vegetarian"]
        < kg["pescatarian"]
        < kg["mixed"]
        < kg["meat_heavy"]
    )
    assert kg["mixed"] == pytest.approx(7.227, abs=0.001)


# ── Flights ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "o,d,cabin,expected,key",
    [
        # 5,539.8 km x 0.11704 (long-haul economy, with RF)
        ("LHR", "JFK", "economy", 648.4, "long_haul.economy"),
        ("LHR", "JFK", "first", 2593.4, "long_haul.first"),
        # 1,444.1 km x 0.12576 (short-haul economy); premium falls back to economy
        ("LHR", "FCO", "economy", 181.6, "short_haul.economy"),
        ("LHR", "FCO", "premium_economy", 181.6, "short_haul.economy"),
        ("LHR", "FCO", "business", 272.4, "short_haul.business"),
        # 347.6 km x 0.22928 (domestic band: average passenger)
        ("LHR", "CDG", "business", 79.7, "domestic.average"),
    ],
)
def test_flight_desnz_bands_and_cabins(o, d, cabin, expected, key):
    out = carbon.compute(
        {
            "search": {**TRIP, "num_travelers": 1},
            "selections": {"flight": {"outbound": leg(o, d)}},
            "cabin": cabin,
        }
    )
    (ln,) = lines(out, "flight_factor")
    assert ln["method"] == "factor"
    assert ln["kg"] == pytest.approx(expected, abs=0.1)
    assert ln["params"]["factor_keys"] == [key]
    assert out["cabin"] == cabin
    assert "flight_desnz" in codes(out)


def test_flight_travellers_multiply_and_round_trip_sums():
    one = carbon.compute(
        {
            "search": {**TRIP, "num_travelers": 1},
            "selections": {"flight": {"outbound": leg("LHR", "JFK")}},
        }
    )
    two = carbon.compute(
        {
            "search": {**TRIP, "num_travelers": 2},
            "selections": {
                "flight": {"outbound": leg("LHR", "JFK"), "return": leg("JFK", "LHR")}
            },
        }
    )
    f1 = sum(ln["kg"] for ln in lines(one, category="flights"))
    f2 = sum(ln["kg"] for ln in lines(two, category="flights"))
    assert f2 == pytest.approx(4 * f1, abs=0.2)


def test_connecting_flight_sums_great_circle_hops():
    out = carbon.compute(
        {
            "search": {**TRIP, "num_travelers": 1},
            "selections": {
                "flight": {
                    "outbound": {
                        **leg("LHR", "JFK"),
                        "stops": 1,
                        "layovers": [{"airport": "DUB", "duration_hours": 2}],
                    }
                }
            },
        }
    )
    (ln,) = lines(out, "flight_factor")
    a, b, c = (carbon.airport(x) for x in ("LHR", "DUB", "JFK"))
    km1 = carbon._km(a, b)  # 449 km: domestic band
    km2 = carbon._km(b, c)  # long-haul
    f = carbon.factors()["flight"]
    expected = (
        km1 * f["domestic.average"]["value"] + km2 * f["long_haul.economy"]["value"]
    )
    assert ln["kg"] == pytest.approx(expected, abs=0.1)
    assert ln["params"]["factor_keys"] == ["domestic.average", "long_haul.economy"]


def test_tim_per_leg_is_measured_and_multiplied():
    out = carbon.compute(
        {
            "search": TRIP,  # 2 travellers
            "selections": {
                "flight": {
                    "outbound": leg(
                        "LHR",
                        "CDG",
                        emissions={
                            "kg_co2e_per_pax": 50,
                            "cabin": "economy",
                            "by_class": {"economy": 50, "business": 75},
                        },
                    ),
                    "return": leg(
                        "CDG",
                        "LHR",
                        emissions={
                            "kg_co2e_per_pax": 55,
                            "cabin": "economy",
                            "by_class": {"economy": 55, "business": 80},
                        },
                    ),
                    "emissions": {"kg_co2e_per_pax": 105, "by_class": {"economy": 105}},
                }
            },
        }
    )
    tim = lines(out, "flight_tim")
    assert [ln["kg"] for ln in tim] == [100.0, 110.0]
    assert all(ln["method"] == "measured_tim" for ln in tim)
    assert out["sources"][0]["id"] == "google_tim"
    # Business uses TIM's per-class figure
    biz = carbon.compute(
        {
            "search": TRIP,
            "cabin": "business",
            "selections": {
                "flight": {
                    "outbound": leg(
                        "LHR",
                        "CDG",
                        emissions={
                            "kg_co2e_per_pax": 50,
                            "cabin": "economy",
                            "by_class": {"economy": 50, "business": 75},
                        },
                    )
                }
            },
        }
    )
    assert lines(biz, "flight_tim")[0]["kg"] == 150.0


def test_tim_whole_result_only_counts_once():
    """An older backend puts one figure on the result, none on the legs."""
    out = carbon.compute(
        {
            "search": TRIP,
            "selections": {
                "flight": {
                    "outbound": leg("LHR", "CDG"),
                    "return": leg("CDG", "LHR"),
                    "emissions": {
                        "kg_co2e_per_pax": 105,
                        "cabin": "economy",
                        "by_class": {"economy": 105},
                    },
                }
            },
        }
    )
    (ln,) = lines(out, category="flights")
    assert ln["method"] == "measured_tim" and ln["kg"] == 210.0
    assert ln["params"]["route"] == "LHR–CDG / CDG–LHR"


def test_multi_city_flights_sum_every_leg_with_tim():
    flights = [
        {
            "leg_index": 0,
            **leg("LHR", "CDG", emissions={"kg_co2e_per_pax": 40, "cabin": "economy"}),
        },
        {
            "leg_index": 1,
            **leg("CDG", "FCO", emissions={"kg_co2e_per_pax": 90, "cabin": "economy"}),
        },
        {
            "leg_index": 2,
            **leg("FCO", "LHR", emissions={"kg_co2e_per_pax": 110, "cabin": "economy"}),
        },
    ]
    out = carbon.compute(
        {
            "search": {**TRIP, "num_travelers": 1, "destinations": ["Paris", "Rome"]},
            "selections": {"flights": flights},
        }
    )
    assert [ln["kg"] for ln in lines(out, "flight_tim")] == [40.0, 90.0, 110.0]
    assert next(c for c in out["categories"] if c["key"] == "flights")["kg"] == 240.0
    # Every move is flown: no inter-city ground line
    assert not lines(out, "intercity")


def test_unknown_airport_is_left_out_with_a_note():
    out = carbon.compute(
        {"search": TRIP, "selections": {"flight": {"outbound": leg("ZZZ", "QQQ")}}}
    )
    assert not lines(out, category="flights")
    assert "flight_unknown_airport" in codes(out)


def test_results_mode_takes_cheapest_flight_and_counts_stays():
    results = {
        "flights": {
            "results": [
                {"outbound": leg("LHR", "CDG")},
                {"outbound": leg("LHR", "JFK")},
            ]
        },
        "hotels": {"results": [{"name": "H", "country_code": "FR"}]},
    }
    out = carbon.compute({"search": TRIP, "results": results})
    (ln,) = lines(out, category="flights")
    assert ln["params"]["route"] == "LHR–CDG"
    assert "flights_cheapest" in codes(out)
    assert lines(out, "hotel_nights")


# ── Lower-carbon hint ────────────────────────────────────────────────────────


def test_rail_hint_for_short_flights_merges_both_ways():
    out = carbon.compute(
        {
            "search": TRIP,
            "selections": {
                "flight": {"outbound": leg("LHR", "CDG"), "return": leg("CDG", "LHR")}
            },
        }
    )
    (h,) = out["lower_carbon"]
    assert h["legs"] == 2 and h["factor"] == "rail_international"
    # 347.6 km x 1.2 route factor
    assert h["rail_km"] == 417
    assert h["rail_kg"] == pytest.approx(2 * 2 * 417.1 * 0.01135, abs=0.2)
    assert h["saving_kg"] == pytest.approx(h["flight_kg"] - h["rail_kg"], abs=0.1)


@pytest.mark.parametrize(
    "o,d,hint",
    [
        ("FRA", "MUC", "rail_national"),
        ("LHR", "DUB", None),
        ("JFK", "LAX", None),
        ("LHR", "FCO", None),
    ],
)
def test_rail_hint_only_where_a_train_is_plausible(o, d, hint):
    out = carbon.compute(
        {"search": TRIP, "selections": {"flight": {"outbound": leg(o, d)}}}
    )
    assert [h["factor"] for h in out["lower_carbon"]] == ([hint] if hint else [])


# ── Stays ────────────────────────────────────────────────────────────────────


def test_stays_country_factor_nights_rooms():
    out = carbon.compute(
        {
            "search": {**TRIP, "num_travelers": 3},
            "selections": {"hotel": {"name": "Le H"}},
        }
    )
    (ln,) = lines(out, "hotel_nights")
    # Paris -> FR 6.7 kg per room-night x 4 nights x 2 rooms (3 travellers)
    assert ln["kg"] == pytest.approx(6.7 * 4 * 2)
    assert ln["method"] == "factor" and ln["params"]["country"] == "FR"
    assert "rooms_default" in codes(out)
    explicit = carbon.compute(
        {
            "search": {**TRIP, "num_travelers": 3},
            "rooms": 3,
            "selections": {"hotel": {"name": "Le H"}},
        }
    )
    assert lines(explicit, "hotel_nights")[0]["kg"] == pytest.approx(6.7 * 4 * 3)


def test_stays_without_country_factor_is_a_labelled_estimate():
    out = carbon.compute(
        {
            "search": {**TRIP, "destination": "Reykjavik", "num_travelers": 1},
            "selections": {"hotel": {"name": "Hotel Borg"}},
        }
    )
    (ln,) = lines(out, "hotel_nights")
    assert ln["method"] == "estimate"
    assert ln["kg"] == pytest.approx(33.5 * 4)
    assert "hotel_default" in codes(out)


def test_plan_without_hotel_leaves_stays_out():
    out = carbon.compute({"search": TRIP, "selections": {}})
    assert not lines(out, category="stays")
    assert "stays_none" in codes(out)
    assert (
        next(c for c in out["categories"] if c["key"] == "stays")["included"] is False
    )


def test_multi_city_stays_split_nights_per_country():
    out = carbon.compute(
        {
            "search": {
                **TRIP,
                "num_travelers": 2,
                "destinations": ["Paris", "Tokyo"],
                "destination_nights": [1, 3],
            },
            "selections": {"hotel": {"name": "x"}},
        }
    )
    got = {ln["params"]["country"]: ln["kg"] for ln in lines(out, "hotel_nights")}
    assert got == {"FR": pytest.approx(6.7), "JP": pytest.approx(39 * 3)}


# ── Ground ───────────────────────────────────────────────────────────────────


def _itin(points_per_day):
    return {
        "days": [
            {
                "day_number": i + 1,
                "slots": [{"activity": "Walk", "lat": la, "lng": lo} for la, lo in pts],
            }
            for i, pts in enumerate(points_per_day)
        ]
    }


def test_ground_measured_km_from_itinerary_with_picked_mode():
    # Two stops 0.1 degree of latitude apart = 11.12 km
    itin = _itin([[(48.8, 2.3), (48.9, 2.3)], []])
    out = carbon.compute(
        {
            "search": {**TRIP, "num_travelers": 5},
            "selections": {"getting_around": [{"type": "taxi", "scope": "intra_city"}]},
            "itinerary": itin,
        }
    )
    (m,) = lines(out, "local_measured")
    km = 11.1195
    # Taxi is per vehicle: 5 travellers need 2 taxis
    assert m["kg"] == pytest.approx(km * 0.20806 * 2, abs=0.1)
    assert m["method"] == "factor"
    (e,) = lines(out, "local_estimate")  # day 2 has no stops
    assert e["method"] == "estimate" and e["params"]["days"] == 1
    assert e["kg"] == pytest.approx(10 * 0.20806 * 2, abs=0.1)


def test_ground_public_transport_is_per_passenger_and_walking_is_zero():
    itin = _itin([[(48.8, 2.3), (48.9, 2.3)]])
    out = carbon.compute(
        {
            "search": {**TRIP, "num_travelers": 2},
            "selections": {"getting_around": [{"type": "metro"}, {"type": "walking"}]},
            "itinerary": itin,
        }
    )
    (m,) = lines(out, "local_measured")
    assert m["kg"] == pytest.approx(11.1195 * 0.5 * 0.01549 * 2, abs=0.05)


def test_ground_without_itinerary_is_a_per_day_estimate_with_default_mix():
    out = carbon.compute({"search": TRIP, "selections": {}})
    (e,) = lines(out, "local_estimate")
    g = carbon.factors()["ground"]
    per_km = (
        0.4 * g["metro"]["value"] * 2
        + 0.4 * g["bus_local"]["value"] * 2
        + 0.2 * g["taxi_vehicle"]["value"]
    )
    assert e["kg"] == pytest.approx(40 * per_km, abs=0.05)
    assert {"ground_default_mix", "ground_per_day"} <= codes(out)


def test_far_apart_stops_are_not_a_local_hop():
    itin = _itin([[(48.85, 2.35), (45.75, 4.85)]])  # Paris -> Lyon, 390 km
    out = carbon.compute({"search": TRIP, "selections": {}, "itinerary": itin})
    assert lines(out, "local_measured")[0]["params"]["km"] == 0


def test_intercity_without_a_flight_goes_by_train():
    out = carbon.compute(
        {
            "search": {**TRIP, "num_travelers": 1, "destinations": ["Paris", "Lyon"]},
            "selections": {"flights": [{"leg_index": 0, **leg("LHR", "CDG")}]},
        }
    )
    (ln,) = lines(out, "intercity")
    km = carbon._km(carbon.place("Paris"), carbon.place("Lyon")) * 1.2
    assert ln["kg"] == pytest.approx(km * 0.03092, abs=0.1)
    assert ln["params"]["mode"] == "rail_national"


# ── Food and activities ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "diet,per_day", [("mixed", 7.227), ("vegan", 2.863), ("vegetarian", 4.367)]
)
def test_food_by_diet(diet, per_day):
    out = carbon.compute({"search": TRIP, "selections": {}, "diet": diet})
    (ln,) = lines(out, "meals")
    assert ln["kg"] == pytest.approx(per_day * 4 * 2, abs=0.1)
    assert ln["method"] == "estimate" and ln["source"] == "owid_food"
    assert out["diet"] == diet


def test_missing_dates_use_default_nights():
    out = carbon.compute(
        {"search": {"destination": "Paris", "num_travelers": 1}, "selections": {}}
    )
    assert out["nights"] == 7
    assert "nights_default" in codes(out)


def test_activities_estimate_transport_heavy_ones_only():
    itin = {
        "days": [
            {
                "slots": [
                    {"activity": "Seine river cruise"},
                    {"activity": "Louvre museum"},
                    {"activity": "Helicopter tour over Paris"},
                    {"activity": "Day trip to Versailles"},
                ]
            }
        ]
    }
    out = carbon.compute({"search": TRIP, "selections": {}, "itinerary": itin})
    acts = lines(out, category="activities")
    assert [a["params"]["rule"] for a in acts] == ["boat", "coach_tour"]
    assert all(a["method"] == "estimate" for a in acts)
    assert acts[0]["kg"] == pytest.approx(20 * 0.01871 * 2, abs=0.05)
    assert acts[1]["kg"] == pytest.approx(100 * 0.03948 * 2, abs=0.05)
    assert {"activities_partial", "activities_unmodelled"} <= codes(out)


# ── Totals ───────────────────────────────────────────────────────────────────


def test_totals_categories_comparisons_and_determinism():
    req = {
        "search": TRIP,
        "selections": {
            "flight": {"outbound": leg("LHR", "JFK")},
            "hotel": {"name": "x"},
        },
    }
    a, b = carbon.compute(json.loads(json.dumps(req))), carbon.compute(req)
    assert a == b
    total = sum(ln["kg"] for ln in a["lines"])
    assert a["total_kg"] == pytest.approx(total, abs=0.3)
    assert a["per_person_kg"] == pytest.approx(a["total_kg"] / 2, abs=0.1)
    assert [c["key"] for c in a["categories"]] == list(carbon.CATEGORIES)
    assert sum(c["share"] for c in a["categories"]) == pytest.approx(1, abs=0.001)
    assert a["comparisons"]["car_km"] == round(a["total_kg"] / 0.16591)
    assert a["comparisons"]["budget_share"] == pytest.approx(
        a["per_person_kg"] / 2000, abs=1e-4
    )
    assert {s["id"] for s in a["sources"]} >= {"desnz_2026", "owid_food"}
    assert all(math.isfinite(ln["kg"]) for ln in a["lines"])


# ── API ──────────────────────────────────────────────────────────────────────


def test_api_ok_anonymous(client):
    r = client.post(
        "/api/carbon/trip",
        json={"search": TRIP, "selections": {"hotel": {"name": "x"}}},
    )
    assert r.status_code == 200
    assert r.json()["total_kg"] > 0


@pytest.mark.parametrize(
    "body",
    [
        {"search": TRIP},
        {"search": TRIP, "selections": {}, "results": {}},
        {"search": TRIP, "selections": {}, "diet": "carnivore"},
        {"search": TRIP, "selections": {}, "rooms": 0},
    ],
)
def test_api_validation(client, body):
    assert client.post("/api/carbon/trip", json=body).status_code == 422


def test_api_off_is_404(client, monkeypatch):
    monkeypatch.setattr(settings, "carbon_footprint_enabled", False)
    r = client.post("/api/carbon/trip", json={"search": TRIP, "selections": {}})
    assert r.status_code == 404
    assert client.get("/api/config").json()["features"]["carbon"] == 0


def test_api_body_cap(client):
    big = {"search": TRIP, "selections": {"pad": "x" * (600 * 1024)}}
    assert client.post("/api/carbon/trip", json=big).status_code == 413


def test_api_rate_limited_in_own_bucket(client, monkeypatch):
    from app.core import rate_limit

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_carbon", 2)
    monkeypatch.setattr(rate_limit, "limiter", rate_limit.SlidingWindowLimiter())
    body = {"search": TRIP, "selections": {}}
    codes_ = [client.post("/api/carbon/trip", json=body).status_code for _ in range(3)]
    assert codes_ == [200, 200, 429]


def test_picked_activities_join_the_itinerary_without_double_counting():
    itin = {"days": [{"slots": [{"activity": "Evening Seine cruise with dinner"}]}]}
    out = carbon.compute(
        {
            "search": TRIP,
            "selections": {
                "activities": [
                    {"name": "Seine cruise"},
                    {"name": "Day trip to Giverny"},
                ]
            },
            "itinerary": itin,
        }
    )
    assert [a["params"]["rule"] for a in lines(out, category="activities")] == [
        "boat",
        "coach_tour",
    ]


# ── Review fixes ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,cc", [("Kyoto", "JP"), ("Bali", "ID"), ("Santorini", "GR")]
)
def test_place_without_own_coordinates_keeps_country_and_borrows_airport(name, cc):
    p = carbon.place(name)
    assert p is not None and p[2] == cc
    assert p[0] is not None and p[1] is not None


def test_kyoto_stay_uses_the_japan_factor():
    out = carbon.compute(
        {
            "search": {**TRIP, "destination": "Kyoto", "num_travelers": 2},
            "selections": {"hotel": {"name": "Ryokan"}},
        }
    )
    (ln,) = lines(out, "hotel_nights")
    jp = carbon.factors()["hotel"]["by_country"]["JP"]["value"]
    assert ln["method"] == "factor" and ln["params"]["country"] == "JP"
    assert ln["kg"] == pytest.approx(jp * 4 * 1)
    assert "hotel_default" not in codes(out)


def test_tokyo_to_kyoto_intercity_is_counted():
    out = carbon.compute(
        {
            "search": {**TRIP, "num_travelers": 1, "destinations": ["Tokyo", "Kyoto"]},
            "selections": {"flights": [{"leg_index": 0, **leg("LHR", "HND")}]},
        }
    )
    (ln,) = lines(out, "intercity")
    assert ln["params"]["route"] == "Tokyo – Kyoto"
    assert 300 < ln["params"]["km"] < 700
    assert "intercity_unknown" not in codes(out)


def test_lookup_errors_are_not_cached(monkeypatch):
    import app.db.database as database

    carbon._airport_row.cache_clear()
    real = database.get_connection

    def boom():
        raise RuntimeError("db locked")

    monkeypatch.setattr(database, "get_connection", boom)
    assert carbon.airport("CDG") is None
    monkeypatch.setattr(database, "get_connection", real)
    assert carbon.airport("CDG") is not None
    assert carbon.airport("ZZZ") is None


@pytest.mark.parametrize(
    "activity",
    [
        "Shopping on Rodeo Drive",
        "Stroll the Quadrilatero della Moda",
        "Lunch at the Ferry Building",
        "Coffee at the Boathouse cafe",
        "Drinks on Boat Quay",
        "Hidden Gems Walk",
    ],
)
def test_activity_rules_match_whole_words_only(activity):
    itin = {"days": [{"slots": [{"activity": activity}]}]}
    out = carbon.compute({"search": TRIP, "selections": {}, "itinerary": itin})
    assert lines(out, category="activities") == []


@pytest.mark.parametrize(
    "activity,rule",
    [
        ("Sunset boat trips", "boat"),
        ("Quad biking in the dunes", "car_tour"),
        ("ATVs at the canyon", "car_tour"),
        ("Morning game drive", "car_tour"),
        ("Bus tours of the city", "coach_tour"),
    ],
)
def test_activity_rules_still_match_real_ones(activity, rule):
    itin = {"days": [{"slots": [{"activity": activity}]}]}
    out = carbon.compute({"search": TRIP, "selections": {}, "itinerary": itin})
    assert [a["params"]["rule"] for a in lines(out, category="activities")] == [rule]


def test_measured_day_trip_is_not_counted_twice_and_slots_dedupe():
    itin = {
        "days": [
            {
                "slots": [
                    {"activity": "Hotel", "lat": 35.0116, "lng": 135.7681},
                    {"activity": "Day trip to Nara", "lat": 34.6851, "lng": 135.8048},
                ]
            },
            {
                "slots": [
                    {"activity": "Arashiyama boat ride"},
                    {"activity": "Arashiyama  Boat ride"},
                    {"activity": "Excursion to Himeji"},
                ]
            },
        ]
    }
    out = carbon.compute(
        {
            "search": {**TRIP, "destination": "Kyoto"},
            "selections": {},
            "itinerary": itin,
        }
    )
    assert lines(out, "local_measured")
    acts = lines(out, category="activities")
    assert [a["params"]["name"] for a in acts] == [
        "Arashiyama boat ride",
        "Excursion to Himeji",
    ]


def test_results_mode_picks_the_lowest_price_per_leg():
    results = {
        "flights": {
            "legs": [
                {
                    "results": [
                        {"leg_index": 0, "price_usd": 0, **leg("LHR", "JFK")},
                        {"leg_index": 0, "price_usd": 500, **leg("LHR", "BCN")},
                        {"leg_index": 0, "price_usd": 120, **leg("LHR", "CDG")},
                    ]
                }
            ]
        }
    }
    out = carbon.compute({"search": TRIP, "results": results})
    (ln,) = lines(out, category="flights")
    assert ln["params"]["route"] == "LHR–CDG"
