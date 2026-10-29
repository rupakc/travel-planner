"""Typed city names resolve to airport codes from the local airports DB.

Live flight search and the fare calendar need real codes; free text like
"Berlin" or "BER — Berlin, Germany" is looked up by exact city name, never
on the web.
"""

from datetime import date

import pytest

from app.db.database import get_connection, lookup_city_iata
from app.schemas.request import TravelSearchRequest
from app.services.serp_flights import _build_params


@pytest.fixture(autouse=True)
def seeded_db(client):
    """The session client seeds the airports table on startup."""


@pytest.fixture(autouse=True)
def no_web(monkeypatch):
    def _fail(*_a, **_kw):
        raise AssertionError("city → airport resolution must not hit the web")

    monkeypatch.setattr("app.db.database._web_search_iata", _fail)
    monkeypatch.setattr("app.db.database._llm_extract_city_country", _fail)


@pytest.fixture
def extra_airports():
    """Insert test-only airports; removed afterwards."""
    codes: list[str] = []

    def add(code: str, city: str, country: str, country_code: str | None) -> None:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO airports (iata_code, name, city, country, country_code)"
                " VALUES (?, ?, ?, ?, ?)",
                (code, f"{city} Test Airport", city, country, country_code),
            )
        codes.append(code)

    yield add
    with get_connection() as conn:
        conn.executemany(
            "DELETE FROM airports WHERE iata_code = ?", [(c,) for c in codes]
        )


def _req(origin: str, destination: str, **kw) -> TravelSearchRequest:
    return TravelSearchRequest(
        origin=origin,
        destination=destination,
        departure_date=date(2026, 12, 1),
        return_date=date(2026, 12, 8),
        nationality="American",
        **kw,
    )


# ── lookup_city_iata ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "place", ["Berlin", "berlin", "Berlin, Germany", "BER — Berlin, Germany"]
)
def test_berlin_forms_resolve_to_ber(place):
    assert lookup_city_iata(place) == "BER"


def test_london_returns_up_to_three_airports_primary_first():
    codes = lookup_city_iata("London").split(",")
    assert 1 <= len(codes) <= 3
    assert codes[0] == "LHR"


@pytest.mark.parametrize(
    "place", ["London, UK", "London, United Kingdom", "London, GB", "London, England"]
)
def test_country_aliases_accepted(place):
    assert lookup_city_iata(place).split(",")[0] == "LHR"


@pytest.mark.parametrize("place", ["Paris, Texas", "Paris, TX", "Berlin, Japan"])
def test_city_not_in_stated_country_resolves_to_nothing(place):
    assert lookup_city_iata(place) is None


def test_us_state_restricts_to_united_states():
    assert lookup_city_iata("Denver, CO") == "DEN"  # CO: Colorado, not Colombia


def test_ambiguous_city_without_country(extra_airports):
    extra_airports("ZQA", "Springfield", "United States", "US")
    extra_airports("ZQB", "Springfield", "United States", "US")
    assert lookup_city_iata("Springfield") == "ZQA,ZQB"  # one country → pick

    extra_airports("ZQC", "Springfield", "Australia", "AU")
    assert lookup_city_iata("Springfield") is None  # two countries → none
    assert lookup_city_iata("Springfield, Australia") == "ZQC"


def test_unknown_city_and_codes():
    assert lookup_city_iata("Atlantis") is None
    assert lookup_city_iata("") is None
    assert lookup_city_iata("lhr") == "LHR"


# ── TravelSearchRequest validator ──────────────────────────────────────────


def test_request_resolves_typed_cities():
    req = _req("Berlin, Germany", "BER — Berlin, Germany")
    assert req.origin_iata == "BER"
    assert req.destination_iata == "BER"
    assert req.origin == "Berlin, Germany"  # display text untouched


def test_request_codes_pass_through_unchanged():
    req = _req("LHR", "jfk")
    assert req.origin_iata == "LHR"
    assert req.destination_iata == "JFK"


def test_request_unknown_city_leaves_codes_unset():
    req = _req("Atlantis", "Paris, Texas")
    assert req.origin_iata is None
    assert req.destination_iata is None


def test_build_params_uses_resolved_code_list():
    req = _req("London", "Berlin")
    params = _build_params("k", req, None)
    assert params["departure_id"] == lookup_city_iata("London")
    assert params["departure_id"].startswith("LHR,")
    assert params["arrival_id"] == "BER"


def test_calendar_params_keep_resolved_codes():
    """The fare calendar builds params from a shifted model_copy."""
    req = _req("London", "Berlin")
    shifted = req.model_copy(update={"departure_date": date(2026, 12, 2)})
    params = _build_params("k", shifted, None)
    assert params["departure_id"].startswith("LHR,")
    assert params["arrival_id"] == "BER"


def test_known_airport_prefix_wins_over_city():
    assert lookup_city_iata("LGW — London, United Kingdom") == "LGW"
    assert lookup_city_iata("lgw - London") == "LGW"


def test_unknown_prefix_keeps_text_whole():
    """Only a known airport code counts as a label prefix."""
    assert lookup_city_iata("ZZZ — Berlin, Germany") is None


def test_airports_db_does_not_import_agents():
    import ast
    from pathlib import Path

    import app.db.database as db

    tree = ast.parse(Path(db.__file__).read_text())
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any("agents" in m for m in modules)


def test_web_saved_row_does_not_make_city_ambiguous(extra_airports):
    """Web-resolved rows carry an LLM country name and no country_code."""
    extra_airports("BQH", "London", "UK", None)
    assert lookup_city_iata("London") == "LHR,LGW,STN"
    assert lookup_city_iata("London, UK") == "LHR,LGW,STN"


def test_uncoded_row_alone_still_resolves(extra_airports):
    extra_airports("ZQD", "Webville", "Freedonia", None)
    assert lookup_city_iata("Webville") == "ZQD"


@pytest.mark.parametrize(
    ("place", "codes"),
    [
        ("Toronto, ON", "YYZ"),
        ("Vancouver, BC", "YVR"),
        ("Munich, Bavaria", "MUC"),  # unrecognised region: city alone
        ("Perth, WA", "PER"),  # WA: Washington or Western Australia
    ],
)
def test_region_suffix_does_not_reject_the_city(place, codes):
    assert lookup_city_iata(place) == codes


@pytest.mark.anyio
async def test_multi_city_leg_with_province_suffix(monkeypatch):
    from app.services import serp_flights

    calls = []

    async def fake_call(params):
        calls.append((params["departure_id"], params["arrival_id"]))
        return {"best_flights": [], "other_flights": []}

    monkeypatch.setattr(serp_flights, "_call", fake_call)
    req = _req("JFK", "Paris, France", destinations=["Toronto, ON", "Paris, France"])
    try:
        await serp_flights.search_multi_city("k", req)
    except serp_flights.SerpAPIError:
        pass  # every leg empty — only the resolved codes matter here
    assert calls[0] == ("JFK", "YYZ")
    assert ("YYZ", "CDG,ORY") in calls


# ── State / province narrows a city's airports ─────────────────────────────


def test_every_us_ca_au_br_airport_has_a_region():
    from app.core.places import _REGION_CODES
    from app.db.airport_regions import AIRPORT_REGION
    from app.db.seed_airports import AIRPORTS

    regional = {a[0]: a[5] for a in AIRPORTS if a[5] in ("US", "CA", "AU", "BR")}
    missing = sorted(set(regional) - set(AIRPORT_REGION))
    assert not missing, f"no region for {missing}"
    assert set(AIRPORT_REGION) <= set(regional), "region for a non-seed airport"
    for code, country in regional.items():
        assert country in _REGION_CODES.get(AIRPORT_REGION[code], ()), code


@pytest.mark.parametrize(
    ("place", "codes"),
    [
        ("Portland", None),  # Oregon and Maine: ambiguous
        ("Portland, OR", "PDX"),
        ("Portland, Oregon", "PDX"),
        ("Portland, Maine", "PWM"),
        ("Portland, ME", "PWM"),
        ("Birmingham, AL", "BHM"),
        ("Birmingham, UK", "BHX"),
        ("San Jose, CA", "SJC"),  # California, not Costa Rica
        ("Victoria, BC", "YYJ"),
        ("Toronto, CA", "YYZ"),  # CA as Canada still names the country
        ("Portland, TX", None),  # no Portland airport in Texas
    ],
)
def test_state_narrows_city_airports(place, codes):
    assert lookup_city_iata(place) == codes


def test_springfield_il_when_seeded():
    from app.db.seed_airports import AIRPORTS

    if not any(a[3] == "Springfield" for a in AIRPORTS):
        pytest.skip("no Springfield in the seed")
    assert lookup_city_iata("Springfield, IL")


def test_city_in_one_region_unaffected():
    assert lookup_city_iata("London") == "LHR,LGW,STN"
    assert lookup_city_iata("New York") == "JFK,LGA"
    assert lookup_city_iata("Houston, TX") == "IAH,HOU"
