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

    def add(
        code: str,
        city: str,
        country: str,
        country_code: str | None,
        region: str | None = None,
    ) -> None:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO airports (iata_code, name, city, country, country_code,"
                " region) VALUES (?, ?, ?, ?, ?, ?)",
                (code, f"{city} Test Airport", city, country, country_code, region),
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


@pytest.mark.parametrize("place", ["Berlin, Japan", "Xyzzyville, France"])
def test_city_not_in_stated_country_resolves_to_nothing(place):
    assert lookup_city_iata(place) is None


@pytest.mark.parametrize("place", ["Paris, Texas", "Paris, TX"])
def test_paris_texas_is_the_texas_town_never_paris_france(place):
    """The Texas town flies from Dallas (final-review link order: a large
    airport leads a medium one unless that is over 3.3× nearer)."""
    codes = lookup_city_iata(place)
    assert codes == "DAL,DFW"
    assert "CDG" not in codes


def test_us_state_restricts_to_united_states():
    assert lookup_city_iata("Denver, CO") == "DEN,BJC"  # Colorado, not Colombia


def test_ambiguous_city_without_country(extra_airports):
    extra_airports("ZQA", "Springfield", "United States", "US")
    extra_airports("ZQB", "Springfield", "United States", "US")
    assert lookup_city_iata("Springfield") == "ZQA,ZQB"  # one country → pick

    extra_airports("ZQC", "Springfield", "Australia", "AU")
    assert lookup_city_iata("Springfield") is None  # two countries → none
    assert lookup_city_iata("Springfield, Australia") == "ZQC"


def test_unknown_city_and_codes():
    assert lookup_city_iata("Xyzzyville") is None
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
    req = _req("Xyzzyville", "Berlin, Japan")
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
        ("Toronto, ON", "YYZ,YTZ,YHM"),
        ("Vancouver, BC", "YVR,YYJ"),
        ("Munich, Bavaria", "MUC"),  # Bavaria: a GeoNames admin1 name
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
    assert calls[0] == ("JFK", "YYZ,YTZ,YHM")
    assert ("YYZ,YTZ,YHM", "CDG,ORY,BVA") in calls


# ── State / province narrows a city's airports ─────────────────────────────


def _seeded_regions(code: str) -> frozenset[str]:
    from app.db.airport_regions import airport_regions

    with get_connection() as conn:
        row = conn.execute(
            "SELECT country_code, region FROM airports WHERE iata_code = ?", (code,)
        ).fetchone()
    return airport_regions(code, row["country_code"], row["region"])


def test_every_us_ca_au_br_airport_has_a_region():
    from app.core.places import _REGION_CODES
    from app.db.seed_airports import AIRPORTS

    regional = {a[0]: a[5] for a in AIRPORTS if a[5] in ("US", "CA", "AU", "BR")}
    missing = sorted(code for code in regional if not _seeded_regions(code))
    assert not missing, f"no region for {missing}"
    for code, country in regional.items():
        for region in _seeded_regions(code):
            assert country in _REGION_CODES.get(region, ()), code


@pytest.mark.parametrize(
    ("place", "codes"),
    [
        ("Portland", "PDX"),  # Oregon's dominates Maine's (Task 3)
        ("Portland, OR", "PDX"),
        ("Portland, Oregon", "PDX"),
        ("Portland, Maine", "PWM"),
        ("Portland, ME", "PWM"),
        ("Birmingham, AL", "BHM"),
        ("Birmingham, UK", "BHX,EMA,MAN"),
        ("San Jose, CA", "SJC,OAK,SFO"),  # California, not Costa Rica
        ("Victoria, BC", "YYJ"),
        ("Toronto, CA", "YYZ,YTZ,YHM"),  # CA as Canada still names the country
        ("Portland, TX", "CRP"),  # the Texas town flies from Corpus Christi
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
    assert lookup_city_iata("New York") == "JFK,LGA,EWR"
    assert lookup_city_iata("Houston, TX") == "IAH,HOU"


# ── Accent and alias spellings ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        (" São   Paulo ", "sao paulo"),
        ("Zürich", "zurich"),
        ("Straße", "strasse"),
        ("Tromsø", "tromso"),
        ("Łódź", "lodz"),
        ("Ærø", "aero"),
        ("Œuvre", "oeuvre"),
        ("Đà Nẵng", "da nang"),
        ("Diyarbakır", "diyarbakir"),
        ("Þórshöfn", "thorshofn"),
        ("Ålesund", "alesund"),
    ],
)
def test_fold_place(text, folded):
    from app.core.places import fold_place

    assert fold_place(text) == folded


def test_city_alias_targets_exist_in_seed():
    from app.core.places import CITY_ALIASES
    from app.db.seed_airports import AIRPORTS

    seeded = {a[3] for a in AIRPORTS}
    assert set(CITY_ALIASES.values()) <= seeded


@pytest.mark.parametrize(
    ("place", "codes"),
    [
        ("São Paulo", "GRU,CGH,VCP"),
        ("São Paulo, Brazil", "GRU,CGH,VCP"),
        ("Zürich", "ZRH"),
        ("Düsseldorf", "DUS,CGN,NRN"),
        ("Kraków", "KRK,KTW"),
        ("Malmö", "MMX"),
        ("Reykjavík", "RKV,KEF"),
        ("Washington", "IAD,DCA,BWI"),
        ("Washington, DC", "IAD,DCA,BWI"),
        ("Washington D.C.", "IAD,DCA,BWI"),
        ("Washington DC", "IAD,DCA,BWI"),
        ("Washington, D.C.", "IAD,DCA,BWI"),
        ("Saint Petersburg", "LED"),
        ("St Petersburg", "LED"),
        ("St. Petersburg", "LED"),
        ("Ålesund", "AES,HOV"),
        ("Alesund", "AES,HOV"),
        ("ålesund", "AES,HOV"),
        ("Saigon", "SGN"),
        ("Bombay", "BOM,NMI"),
        ("New York City", "JFK,LGA,EWR"),
        ("NYC", "NYC"),  # bare code wins
    ],
)
def test_accent_and_alias_spellings(place, codes):
    assert lookup_city_iata(place) == codes


# ── Fix round 1: region sets, country-aware regions, full names, St./Saint ──


@pytest.mark.parametrize(
    "place",
    ["Kansas City", "Kansas City, MO", "Kansas City, KS", "Kansas City, Kansas"],
)
def test_kansas_city_serves_both_states(place):
    assert lookup_city_iata(place) == "MCI"


@pytest.mark.parametrize(
    ("place", "codes"),
    [
        ("Columbus, GA", "CSG"),
        ("Charleston, WV", "CRW"),
        ("Rochester, MN", "RST"),
        ("Jackson, WY", "JAC"),
    ],
)
def test_city_in_another_state_is_not_the_curated_one(place, codes):
    """Curated: Columbus OH, Charleston SC, Rochester NY, Jackson MS; the
    stated state's own town resolves through the place data (Task 3)."""
    assert lookup_city_iata(place) == codes


def test_region_match_is_country_aware(extra_airports):
    extra_airports("ZQE", "Testburg", "Australia", "AU", "AU-WA")
    extra_airports("ZQF", "Testburg", "United States", "US", "US-WA")
    assert lookup_city_iata("Testburg, Western Australia") == "ZQE"
    assert lookup_city_iata("Testburg, Washington") == "ZQF"
    assert lookup_city_iata("Testburg, WA") is None  # either country


@pytest.mark.parametrize(
    ("place", "codes"),
    [
        ("Victoria, British Columbia", "YYJ"),
        ("Toronto, Ontario", "YYZ,YTZ,YHM"),
        ("Montreal, Québec", "YUL,YHU,YMX"),
        ("Sydney, New South Wales", "SYD,WSI"),
        ("Perth, Western Australia", "PER"),
        ("Melbourne, Victoria", "MEL,AVV,MEB"),
        ("Rio de Janeiro, Rio de Janeiro", "GIG,SDU"),
        ("São Paulo, São Paulo", "GRU,CGH,VCP"),
        ("Sao Paulo, Sao Paulo", "GRU,CGH,VCP"),
        ("Belém, Pará", "BEL"),
        ("Brasilia, Distrito Federal", "BSB"),
    ],
)
def test_full_region_names(place, codes):
    assert lookup_city_iata(place) == codes


@pytest.mark.parametrize(
    ("place", "codes"),
    [
        ("St. Louis", "STL,BLV"),
        ("St Louis", "STL,BLV"),
        ("Saint Louis", "STL,BLV"),
        ("saint louis, MO", "STL,BLV"),
        ("St Petersburg", "LED"),
        ("Saint Petersburg", "LED"),
        ("St. Petersburg", "LED"),
    ],
)
def test_st_and_saint_spellings(place, codes):
    assert lookup_city_iata(place) == codes


def test_every_airport_region_is_a_set():
    assert _seeded_regions("MCI") == {"mo", "ks"}
    assert _seeded_regions("IAD") == {"va", "dc"}
    assert isinstance(_seeded_regions("PDX"), frozenset)


# ── Task 3: place resolution over the full dataset ─────────────────────────


@pytest.mark.parametrize(
    ("place", "prefix"),
    [
        ("Paris", "CDG,ORY"),  # curated order first
        ("London", "LHR,LGW,STN"),
        ("Washington", "IAD,DCA"),
        ("New York", "JFK,LGA,EWR"),
        ("Frankfurt", "FRA"),
    ],
)
def test_curated_codes_come_first(place, prefix):
    assert lookup_city_iata(place).startswith(prefix)


def test_frankfurt_is_fra_only():
    assert lookup_city_iata("Frankfurt") == "FRA"  # HHN is 115 km away


@pytest.mark.parametrize(
    ("place", "codes"),
    [
        ("Valencia", None),  # Spain's or Venezuela's (bigger)
        ("Valencia, Spain", "VLC"),
        ("San Jose", None),
        ("Springfield", None),
        ("Springfield, IL", "SPI"),
        ("Portland, ME", "PWM"),
        ("Birmingham", "BHX,EMA,MAN"),
        ("Birmingham, AL", "BHM"),
        ("London, ON", "YXU"),
        ("London, Ontario", "YXU"),
        ("Sydney, Nova Scotia", "YQY"),
        ("Kansas City, KS", "MCI"),
        ("Perth, WA", "PER"),
        ("Phnom Penh", "KTI"),
        ("Siem Reap", "SAI"),
        ("Chișinău", "RMO"),
        ("Cancun", "CUN,CZM"),
        ("Bali", "DPS"),
        ("Ubud", "DPS"),
        ("Caracas", "CCS"),
        ("NYC", "NYC"),
        ("LGW — London, United Kingdom", "LGW"),
    ],
)
def test_plan_d_lookups(place, codes):
    assert lookup_city_iata(place) == codes


@pytest.mark.parametrize(
    ("place", "airports"),
    [
        ("Milan", {"MXP", "LIN", "BGY"}),
        ("Milano", {"MXP", "LIN", "BGY"}),
        ("Tokyo", {"HND", "NRT"}),
        ("Kyoto", {"ITM", "KIX"}),
        ("Venice", {"VCE", "TSF"}),
        ("Zermatt", {"ZRH", "GVA", "BRN", "SIR", "LUG"}),
        ("Interlaken", {"ZRH", "GVA", "BRN", "SIR"}),
        ("Interlaken, Switzerland", {"ZRH", "GVA", "BRN", "SIR"}),
    ],
)
def test_places_reach_their_airports(place, airports):
    codes = lookup_city_iata(place).split(",")
    assert codes[0] in airports
    if place.startswith("Mil"):
        assert "MXP" in codes


def test_foreign_links_do_not_join_curated_codes():
    """Zürich's place also links Friedrichshafen (DE); curated ZRH stays alone."""
    assert lookup_city_iata("Zürich") == "ZRH"
    assert lookup_city_iata("Munich, Bavaria") == "MUC"


@pytest.mark.parametrize(
    ("typed", "codes"),
    [("Goa", "GOI,GOX"), ("Kos", "KGS"), ("GOA", "GOA"), ("lhr", "LHR")],
)
def test_three_letter_place_names_are_places_not_codes(typed, codes):
    assert lookup_city_iata(typed) == codes


def test_request_keeps_a_three_letter_place_name():
    req = _req("Goa", "Kos")
    assert (req.origin, req.origin_iata) == ("Goa", "GOI,GOX")
    assert (req.destination, req.destination_iata) == ("Kos", "KGS")


def test_dataset_airport_city_is_the_last_resort(extra_airports):
    """No curated row and no place: a dataset airport serving the typed city
    by display name still resolves."""
    extra_airports("ZQJ", "Qwertyburg", "Testland", "XT")
    with get_connection() as conn:
        conn.execute("UPDATE airports SET type_rank = 2 WHERE iata_code = 'ZQJ'")
    assert lookup_city_iata("Qwertyburg") == "ZQJ"


def test_unscheduled_linked_airport_is_never_returned():
    with get_connection() as conn:
        conn.execute("UPDATE airports SET scheduled = 0 WHERE iata_code = 'TSF'")
    try:
        assert "TSF" not in (lookup_city_iata("Venice") or "")
        assert "TSF" not in (lookup_city_iata("Treviso") or "")
    finally:
        with get_connection() as conn:
            conn.execute("UPDATE airports SET scheduled = 1 WHERE iata_code = 'TSF'")


# ── Fix round 1: code casing, country aliases, no foreign padding ──────────


@pytest.mark.parametrize(
    ("typed", "codes"),
    [
        ("Hue", "HUI,DAD"),  # place first: Huế (own airport first), not Humera
        ("hue", "HUI,DAD"),
        ("Bol", "BWK,SPU"),  # Bol, Croatia (own airport), not Bol, Chad
        ("lhr", "LHR"),  # no such place: the code
        ("jfk", "JFK"),
        ("NYC", "NYC"),  # all caps: the code as typed
        ("BER", "BER"),
        ("HUE", "HUE"),
        ("GOA", "GOA"),
        ("Goa", "GOI,GOX"),
    ],
)
def test_only_all_caps_three_letters_are_codes_first(typed, codes):
    assert lookup_city_iata(typed) == codes


@pytest.mark.parametrize(
    ("typed", "first"),
    [
        ("USA", {"JFK", "LGA", "EWR"}),
        ("usa", {"JFK", "LGA", "EWR"}),
        ("UAE", {"AUH", "DXB", "DWC"}),
        ("uae", {"AUH", "DXB", "DWC"}),
        ("UK", {"LHR", "LCY", "LGW"}),
        ("uk", {"LHR", "LCY", "LGW"}),
    ],
)
def test_country_names_and_aliases_beat_codes(typed, first):
    assert lookup_city_iata(typed).split(",")[0] in first


def test_request_passes_picked_codes_straight_through():
    """The autocomplete submits the picked airport's upper-case code."""
    req = _req("LHR", "HUE")
    assert (req.origin_iata, req.destination_iata) == ("LHR", "HUE")
    req = _req("Hue", "lhr")
    assert (req.origin_iata, req.destination_iata) == ("HUI,DAD", "LHR")
    assert req.origin == "Hue"  # a place name is not rewritten as a code


@pytest.mark.parametrize(
    ("place", "codes"),
    [
        ("Victoria", "YYJ"),  # not Friday Harbor / Roche Harbor (US)
        ("Detroit", "DTW"),  # not Windsor (CA)
        ("Strasbourg", "SXB"),  # not Karlsruhe (DE)
        ("Geneva", "GVA"),  # not Annecy (FR)
        ("San Diego", "SAN,CLD"),  # not Tijuana (MX)
        ("Switzerland", "ZRH"),  # not Friedrichshafen (DE)
        ("Basel", "BSL"),  # BSL (in France) is Basel's own airport
        ("Lviv", "RZE"),  # no domestic airport: the foreign fallback
    ],
)
def test_no_foreign_padding(place, codes):
    assert lookup_city_iata(place) == codes


def test_niagara_falls_never_gets_foreign_padding():
    codes = lookup_city_iata("Niagara Falls")
    assert codes is None or codes.split(",")[0] in {"BUF", "IAG", "YYZ", "YHM"}
