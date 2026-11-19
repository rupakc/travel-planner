"""Trip carbon footprint with the crawler's carbon data
(services/carbon_live.py, docs/Carbon-Footprint.md "Crawler data").

The crawler is always an httpx.MockTransport (conftest refuses real network).
Shapes follow the crawler's /v1/carbon/factors (Item page) and
/v1/carbon/grid (observation list) handlers and tests. The key guarantee:
crawler off, down, or answering nothing usable gives exactly today's answer.
"""

import asyncio
import copy
import json

import httpx
import pytest

from app.core.config import settings
from app.services import carbon, carbon_live, crawler_client

TRIP = {
    "origin": "London",
    "destination": "New York",
    "departure_date": "2026-05-01",
    "return_date": "2026-05-05",
    "num_travelers": 2,
}
OGL = {
    "class": "open",
    "spdx": "OGL-UK-3.0",
    "attribution": "Contains public sector information licensed under the Open "
    "Government Licence v3.0",
    "url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
}
CC_BY = {
    "class": "open",
    "spdx": "CC-BY-4.0",
    "attribution": "Ember, CC BY 4.0",
    "url": "https://creativecommons.org/licenses/by/4.0/",
}
CC_BY_SA = {
    "class": "share_alike",
    "spdx": "CC-BY-SA-4.0",
    "attribution": "Some wiki, CC BY-SA 4.0",
    "url": "https://creativecommons.org/licenses/by-sa/4.0/",
}
NAMES = {
    "od-desnz-ghg-factors": "UK GHG conversion factors (DESNZ)",
    "carbon-ember-grid": "Ember yearly electricity data",
}


def factor(fid, data, *, licence=OGL, conflict=False, year=2027):
    return {
        "id": f"desnz:{year}:{fid}",
        "kind": "emission_factor",
        "schema": "emission_factor@1",
        "title": data.get("activity_label"),
        "excerpt": None,
        "data": {
            "gas_basis": "co2e",
            "scope": "Scope 3",
            "year": year,
            "publisher": "UK Department for Energy Security and Net Zero (DESNZ)",
            "dataset": f"UK GHG conversion factors for company reporting, flat file {year}",
            "factor_id": fid,
            "geography": "United Kingdom",
            "country_code": "GB",
            **data,
        },
        "place_ids": [],
        "licence": licence,
        "provenance": [
            {
                "source_id": "od-desnz-ghg-factors",
                "url": "https://www.gov.uk/government/collections/"
                "government-conversion-factors-for-company-reporting",
                "captured_at": "2027-06-20T08:00:00Z",
            }
        ],
        "conflict": conflict,
        "use_policy": {"index": "full", "serve": "full"},
        "updated_at": "2027-06-20T08:00:00Z",
        "score": None,
    }


LONG_ECO_2027 = factor(
    "21_316_3170_11_1",
    {
        "activity": "flights_long_haul_to_from_uk_economy_class_with_rf",
        "activity_label": "Flights / Long-haul, to/from UK / Economy class / With RF",
        "category": "flights",
        "unit": "kg CO2e per passenger.km",
        "value": 0.11,
        "gas_basis": "co2e_with_rf",
    },
)
LONG_ECO_NO_RF = factor(
    "21_316_3171_11_1",
    {
        "activity": "flights_long_haul_to_from_uk_economy_class_without_rf",
        "activity_label": "Flights / Long-haul, to/from UK / Economy class / Without RF",
        "category": "flights",
        "unit": "kg CO2e per passenger.km",
        "value": 0.06,
        "gas_basis": "co2e_without_rf",
    },
)
HOTEL_US_2027 = factor(
    "29_600_4053_13_1",
    {
        "activity": "hotel_stay_united_states",
        "activity_label": "Hotel stay / United States",
        "category": "accommodation",
        "unit": "kg CO2e per Room per night",
        "value": 15.0,
        "geography": "United States",
        "country_code": "US",
    },
)
METRO_2027 = factor(
    "25_315_3150_11_1",
    {
        "activity": "rail_london_underground",
        "activity_label": "Rail / London Underground",
        "category": "rail",
        "unit": "kg CO2e per passenger.km",
        "value": 0.015,
    },
)
TAXI_PKM_2027 = factor(  # same label, other unit: never the vehicle.km row
    "25_313_3142_11_1",
    {
        "activity": "taxis_regular_taxi",
        "activity_label": "Taxis / Regular taxi",
        "category": "taxi",
        "unit": "kg CO2e per passenger.km",
        "value": 0.9,
    },
)


def grid_point(cc, year, g, *, licence=CC_BY, period="annual", basis="lifecycle"):
    return {
        "series_key": f"grid_ci:{cc}:{period}:{basis}",
        "observed_at": f"{year}-01-01T00:00:00Z",
        "value": {
            "country_code": cc,
            "period": period,
            "basis": basis,
            "year": year,
            "date": f"{year}-01-01",
            "intensity_g_per_kwh": g,
            "publisher": "Ember",
            "dataset": "Yearly electricity data",
            "source_url": "https://ember-energy.org/data/yearly-electricity-data/",
            "as_of": "2026-10-01",
        },
        "source_id": "carbon-ember-grid",
        "licence": licence,
    }


class Crawler:
    """A fake crawler read API: factors per (category, year) and grid points
    per country."""

    def __init__(self, factors=(), grid=None, status=200):
        self.factors = list(factors)
        self.grid = grid or {}
        self.status = status
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "x"})
        q = request.url.params
        path = request.url.path
        if path == "/v1/sources":
            return httpx.Response(
                200,
                json={"items": [{"source_id": k, "name": v} for k, v in NAMES.items()]},
            )
        if path == "/v1/carbon/factors":
            items = [
                f
                for f in self.factors
                if (not q.get("category") or f["data"]["category"] == q["category"])
                and (not q.get("year") or f["data"]["year"] == int(q["year"]))
                and (not q.get("activity") or q["activity"] in f["data"]["activity"])
            ]
            items.sort(key=lambda f: -f["data"]["year"])
            return httpx.Response(
                200,
                json={"items": items[: int(q.get("limit", 20))], "next_cursor": None},
            )
        if path == "/v1/carbon/grid":
            return httpx.Response(200, json={"items": self.grid.get(q["country"], [])})
        return httpx.Response(404, json={"error": "not_found"})

    def paths(self):
        return [c.url.path for c in self.calls]


@pytest.fixture
def crawler_on(monkeypatch):
    monkeypatch.setattr(settings, "crawler_enabled", True)
    monkeypatch.setattr(settings, "crawler_api_url", "https://10.142.0.3:8443")
    monkeypatch.setattr(settings, "crawler_api_token", "voyager.test-secret-0123456789")
    monkeypatch.setattr(settings, "crawler_ca_pem", "")
    monkeypatch.setattr(settings, "crawler_ca_file", "")
    crawler_client.reset()

    def install(handler):
        monkeypatch.setattr(crawler_client, "_transport", httpx.MockTransport(handler))
        return handler

    yield install
    crawler_client.reset()


def leg(o, d):
    return {"origin": o, "destination": d, "stops": 0, "layovers": []}


def plan(hotel_cc="US", **sel):
    return {
        "search": TRIP,
        "selections": {
            "flight": {"outbound": leg("LHR", "JFK"), "return": leg("JFK", "LHR")},
            "hotel": {"name": "Hotel X", "country_code": hotel_cc},
            "getting_around": [{"type": "metro", "scope": "intra_city"}],
            **sel,
        },
        "diet": "mixed",
    }


def static_answer(body):
    """The committed-table answer, computed with the crawler off."""
    return carbon.compute(json.loads(json.dumps(body)))


def post(client, body):
    r = client.post("/api/carbon/trip", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def lines(out, kind):
    return [ln for ln in out["lines"] if ln["kind"] == kind]


# ── unchanged without usable crawler data ────────────────────────────────────


BODIES = [
    plan(),
    plan(hotel_cc="IS"),  # a country DESNZ does not list
    {
        "search": {**TRIP, "destination": "Paris"},
        "results": {
            "flights": {"results": [leg("LHR", "CDG")]},
            "hotels": {"results": [{"name": "H", "country_code": "FR"}]},
        },
    },
]


@pytest.mark.parametrize("body", BODIES)
def test_crawler_off_is_the_static_answer_and_sends_nothing(client, body, monkeypatch):
    seen = []
    monkeypatch.setattr(
        crawler_client, "_transport", httpx.MockTransport(lambda r: seen.append(r))
    )
    assert post(client, body) == static_answer(body)
    assert seen == []


@pytest.mark.parametrize(
    "crawler",
    [
        "down",
        Crawler(status=500),
        Crawler(status=401),
        Crawler(),  # answers, nothing at all
        # Only the committed table's year (or older): nothing newer to use
        Crawler(
            [
                copy.deepcopy(LONG_ECO_2027)
                | {"data": {**LONG_ECO_2027["data"], "year": 2026}}
            ]
        ),
        # Newer, but share-alike, in conflict, or the wrong unit/basis
        Crawler(
            [factor("x", LONG_ECO_2027["data"] | {"value": 0.2}, licence=CC_BY_SA)]
        ),
        Crawler([factor("y", LONG_ECO_2027["data"] | {"value": 0.2}, conflict=True)]),
        Crawler([LONG_ECO_NO_RF, TAXI_PKM_2027]),
        # Grid for IS that is share-alike, monthly, direct or absurd
        Crawler(
            grid={
                "IS": [
                    grid_point("IS", 2025, 28, licence=CC_BY_SA),
                    grid_point("IS", 2025, 28, period="monthly"),
                    grid_point("IS", 2025, 28, basis="direct"),
                    grid_point("IS", 2025, 99999),
                ]
            }
        ),
    ],
    ids=[
        "down",
        "500",
        "401",
        "empty",
        "same-year",
        "share-alike",
        "conflict",
        "unit-basis",
        "bad-grid",
    ],
)
@pytest.mark.parametrize("body", BODIES, ids=["plan", "plan-IS", "results"])
def test_crawler_without_usable_data_is_byte_identical(
    client, crawler_on, crawler, body
):
    def down(request):
        raise httpx.ConnectError("no route to host")

    crawler_on(down if crawler == "down" else crawler)
    r = client.post("/api/carbon/trip", json=body)
    assert r.status_code == 200
    assert r.content == client.post("/api/carbon/trip", json=body).content
    assert r.json() == static_answer(body)
    assert "crawler_sources" not in r.json()


def test_compute_without_overlay_is_unchanged():
    for body in BODIES:
        assert carbon.compute(copy.deepcopy(body)) == carbon.compute(
            copy.deepcopy(body), None
        )


# ── newer DESNZ factors ──────────────────────────────────────────────────────


def test_newer_desnz_factors_replace_matching_rows(client, crawler_on):
    fake = crawler_on(
        Crawler(
            [LONG_ECO_2027, LONG_ECO_NO_RF, HOTEL_US_2027, METRO_2027, TAXI_PKM_2027]
        )
    )
    body = plan()
    out = post(client, body)
    base = static_answer(body)

    fl = lines(out, "flight_factor")
    assert len(fl) == 2
    for ln, old in zip(fl, lines(base, "flight_factor")):
        assert ln["source"] == "crawler_desnz_2027"
        # same distance, new factor: 0.11 instead of 0.11704
        assert ln["kg"] == pytest.approx(old["kg"] * 0.11 / 0.11704, abs=0.2)
        src = ln["crawler_source"]
        assert src["name"] == NAMES["od-desnz-ghg-factors"]
        assert src["url"].startswith("https://www.gov.uk/")
        assert src["as_of"] == "2027-06-20"
        assert src["licence"] == "OGL-UK-3.0"
        assert src["attribution"].startswith("Contains public sector information")
        assert src["year"] == 2027

    hotel = lines(out, "hotel_nights")[0]
    assert hotel["source"] == "crawler_desnz_2027"
    assert hotel["params"]["per_room_night_kg"] == 15.0
    assert hotel["method"] == "factor"

    local = [ln for ln in out["lines"] if ln["category"] == "ground"][0]
    assert local["source"] == "crawler_desnz_2027"  # metro 2027

    # Food is untouched (no newer OWID set)
    assert lines(out, "meals") == lines(base, "meals")
    assert any(
        a["code"] == "factors_newer" and a["params"] == {"year": 2027}
        for a in out["assumptions"]
    )
    ids = [s["id"] for s in out["sources"]]
    assert ids[-1] == "crawler_desnz_2027" and "owid_food" in ids
    assert [s["id"] for s in out["crawler_sources"]] == ["crawler_desnz_2027"]
    # the attribution list is not repeated for the same licence text
    assert len(out["attribution"]) == len(set(out["attribution"]))
    # Probe first, then reads pinned to the newer year
    factor_calls = [c for c in fake.calls if c.url.path == "/v1/carbon/factors"]
    assert factor_calls[0].url.params.get("limit") == "1"
    assert all(c.url.params.get("year") == "2027" for c in factor_calls[1:])
    assert all(
        c.url.params.get("source") == "od-desnz-ghg-factors" for c in factor_calls
    )


def test_a_newer_set_is_read_once_then_cached(client, crawler_on):
    fake = crawler_on(Crawler([LONG_ECO_2027]))
    a = post(client, plan())
    n = len(fake.calls)
    b = post(client, plan())
    assert a == b
    assert len(fake.calls) == n


def test_same_year_crawler_set_costs_one_probe(client, crawler_on):
    same = copy.deepcopy(LONG_ECO_2027)
    same["data"]["year"] = 2026
    fake = crawler_on(Crawler([same]))
    post(client, plan())
    assert fake.paths().count("/v1/carbon/factors") == 1
    assert "/v1/carbon/grid" not in fake.paths()  # US has a hotel factor


# ── grid intensity for countries without a hotel factor ──────────────────────


def test_grid_intensity_for_a_country_without_hotel_factor(client, crawler_on):
    fake = crawler_on(
        Crawler(grid={"IS": [grid_point("IS", 2025, 28.4), grid_point("IS", 2024, 30)]})
    )
    body = plan(hotel_cc="IS")
    out = post(client, body)
    base = static_answer(body)
    assert "IS" not in carbon.factors()["hotel"]["by_country"]

    hotel = lines(out, "hotel_nights")[0]
    assert hotel["method"] == "estimate"
    assert hotel["source"] == "crawler_grid_carbon_ember_grid_is"
    assert hotel["params"]["grid_g_per_kwh"] == 28
    assert hotel["params"]["grid_year"] == 2025
    # 4 nights × 1 room × 28.4 g/kWh × 70 kWh
    assert hotel["kg"] == round(4 * 1 * 0.0284 * 70, 1)
    assert hotel["params"]["per_room_night_kg"] == round(0.0284 * 70, 1)
    src = hotel["crawler_source"]
    assert src["name"] == NAMES["carbon-ember-grid"]
    assert src["url"] == "https://ember-energy.org/data/yearly-electricity-data/"
    assert src["as_of"] == "2026-10-01"
    assert src["licence"] == "CC-BY-4.0"
    assert src["attribution"] == "Ember, CC BY 4.0"

    codes = {a["code"] for a in out["assumptions"]}
    assert "hotel_grid" in codes and "hotel_default" not in codes
    assert "hotel_default" in {a["code"] for a in base["assumptions"]}
    # Everything but the stay is today's answer
    assert [ln for ln in out["lines"] if ln["category"] != "stays"] == [
        ln for ln in base["lines"] if ln["category"] != "stays"
    ]
    assert [s["id"] for s in out["crawler_sources"]] == [
        "crawler_grid_carbon_ember_grid_is"
    ]
    grid_calls = [c for c in fake.calls if c.url.path == "/v1/carbon/grid"]
    assert [c.url.params["country"] for c in grid_calls] == ["IS"]
    assert grid_calls[0].url.params["period"] == "annual"
    assert grid_calls[0].url.params["basis"] == "lifecycle"
    # The source object is shown through SourceLine, where "via" is the
    # forex pivot currency: a crawler source must never carry one
    assert "via" not in src
    assert all("via" not in s for s in out["crawler_sources"])


def test_each_grid_country_keeps_its_own_year(crawler_on, monkeypatch):
    static = carbon.factors()
    assert not {"KE", "MN"} & set(static["hotel"]["by_country"])
    ke = grid_point("KE", 2025, 100)
    mn = grid_point("MN", 2019, 700)
    mn["value"]["as_of"] = "2020-03-01"
    crawler_on(Crawler(grid={"KE": [ke], "MN": [mn]}))
    live = asyncio.run(carbon_live.fetch(static, ["KE", "MN"]))
    assert live is not None
    for cc, year, as_of in (("KE", 2025, "2026-10-01"), ("MN", 2019, "2020-03-01")):
        pt = live["grid"][cc]
        assert pt["year"] == year
        assert pt["source"] == f"crawler_grid_carbon_ember_grid_{cc.lower()}"
        obj = live["sources"][pt["source"]]
        assert obj["year"] == year and obj["as_of"] == as_of
        assert pt["crawler_source"] == obj
    assert len(live["sources"]) == 2


def test_grid_is_not_used_where_desnz_lists_the_country(client, crawler_on):
    fake = crawler_on(Crawler(grid={"FR": [grid_point("FR", 2025, 40)]}))
    body = plan(hotel_cc="FR")
    assert post(client, body) == static_answer(body)
    assert "/v1/carbon/grid" not in fake.paths()


def test_newer_hotel_row_adds_a_country(client, crawler_on):
    iceland = factor(
        "29_600_9999_13_1",
        {
            "activity": "hotel_stay_iceland",
            "activity_label": "Hotel stay / Iceland",
            "category": "accommodation",
            "unit": "kg CO2e per Room per night",
            "value": 3.1,
            "geography": "Iceland",
            "country_code": "IS",
        },
    )
    fake = crawler_on(Crawler([iceland], grid={"IS": [grid_point("IS", 2025, 28)]}))
    out = post(client, plan(hotel_cc="IS"))
    hotel = lines(out, "hotel_nights")[0]
    assert hotel["method"] == "factor"
    assert hotel["params"]["per_room_night_kg"] == 3.1
    assert hotel["source"] == "crawler_desnz_2027"
    assert "/v1/carbon/grid" not in fake.paths()


def _hotel_row(fid, activity, label, value, geography, cc):
    return factor(
        fid,
        {
            "activity": activity,
            "activity_label": label,
            "category": "accommodation",
            "unit": "kg CO2e per Room per night",
            "value": value,
            "geography": geography,
            "country_code": cc,
        },
    )


def test_london_row_never_replaces_the_uk_hotel_factor(client, crawler_on):
    # The crawler maps every "UK…" Level-3 name to GB, so "UK (London)"
    # also arrives as a GB row, and its order is arbitrary: London first here
    london = _hotel_row(
        "29_600_4100_13_1",
        "hotel_stay_uk_london",
        "Hotel stay / UK (London)",
        13.9,
        "United Kingdom",
        "GB",
    )
    uk = _hotel_row(
        "29_600_4099_13_1",
        "hotel_stay_uk",
        "Hotel stay / UK",
        9.9,
        "United Kingdom",
        "GB",
    )
    static_gb = carbon.factors()["hotel"]["by_country"]["GB"]
    assert carbon_live.slug(static_gb["label"]) == "hotel_stay_uk"
    crawler_on(Crawler([london, uk]))
    hotel = lines(post(client, plan(hotel_cc="GB")), "hotel_nights")[0]
    assert hotel["source"] == "crawler_desnz_2027"
    assert hotel["params"]["per_room_night_kg"] == 9.9


def test_london_alone_leaves_the_static_uk_factor(client, crawler_on):
    london = _hotel_row(
        "29_600_4100_13_1",
        "hotel_stay_uk_london",
        "Hotel stay / UK (London)",
        13.9,
        "United Kingdom",
        "GB",
    )
    crawler_on(Crawler([london, LONG_ECO_2027]))
    body = plan(hotel_cc="GB")
    out = post(client, body)
    hotel = lines(out, "hotel_nights")[0]
    assert hotel == lines(static_answer(body), "hotel_nights")[0]


def test_a_new_country_with_several_rows_is_skipped(client, crawler_on):
    # No telling a national row from a regional one: keep today's answer
    region = _hotel_row(
        "29_600_9998_13_1",
        "hotel_stay_iceland_reykjavik",
        "Hotel stay / Iceland (Reykjavik)",
        9.0,
        "Iceland (Reykjavik)",
        "IS",
    )
    national = _hotel_row(
        "29_600_9999_13_1",
        "hotel_stay_iceland",
        "Hotel stay / Iceland",
        3.1,
        "Iceland",
        "IS",
    )
    crawler_on(Crawler([region, national]))
    body = plan(hotel_cc="IS")
    hotel = lines(post(client, body), "hotel_nights")[0]
    assert hotel == lines(static_answer(body), "hotel_nights")[0]


def test_a_new_country_row_must_be_its_national_label(client, crawler_on):
    odd = _hotel_row(
        "29_600_9998_13_1",
        "hotel_stay_iceland_reykjavik",
        "Hotel stay / Iceland (Reykjavik)",
        9.0,
        "Iceland",
        "IS",
    )
    crawler_on(Crawler([odd]))
    body = plan(hotel_cc="IS")
    hotel = lines(post(client, body), "hotel_nights")[0]
    assert hotel == lines(static_answer(body), "hotel_nights")[0]


# ── helpers ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "label,slug",
    [
        (
            "Flights / Long-haul, to/from UK / Economy class / With RF",
            "flights_long_haul_to_from_uk_economy_class_with_rf",
        ),
        ("Hotel stay / Côte d'Ivoire", "hotel_stay_cote_divoire"),
        ("Berries & Grapes", "berries_and_grapes"),
        ("Cars (by size) / Average car / Unknown", "cars_by_size_average_car_unknown"),
        # countries::fold drops a leading "the" and spells "st" as "saint"
        ("The Gambia", "gambia"),
        ("Hotel stay / The Gambia", "hotel_stay_the_gambia"),
        ("St Lucia", "saint_lucia"),
        ("Hotel stay / St. Kitts", "hotel_stay_saint_kitts"),
        ("Bahrain’s", "bahrains"),
    ],
)
def test_slug_matches_the_crawler(label, slug):
    assert carbon_live.slug(label) == slug


def test_unit_keys():
    k = carbon_live.unit_key
    assert (
        k("kg CO2e per room.night") == k("kg CO2e per Room per night") == "room.night"
    )
    assert k("kg CO2e per vehicle.km") == k("kg CO2e per km") == "km"
    assert k("kg CO2e per passenger.km") == "passenger.km"
    assert k("tonnes CO2e per km") is None


def test_fetch_never_raises_and_is_off_unconfigured():
    assert asyncio.run(carbon_live.fetch(carbon.factors(), ["IS"])) is None


def test_fetch_overall_budget(crawler_on, monkeypatch):
    async def slow(**kw):
        await asyncio.sleep(5)

    crawler_on(Crawler())
    monkeypatch.setattr(carbon_live, "FETCH_BUDGET_S", 0.05)
    monkeypatch.setattr(crawler_client, "carbon_factors", slow)
    assert asyncio.run(carbon_live.fetch(carbon.factors(), ["IS"])) is None
