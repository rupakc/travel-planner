"""Reference-table lookups must hit exactly the right row (or none).

The oracle for every input is the country it names: each lookup must return
the row for that country when the table has one, and nothing otherwise.
Inputs cover every table key, every mapped city and every seeded airport in
the forms the app actually sends: bare city, "City, Country" (the IATA
rewrite in TravelSearchRequest), "IATA — City, Country" (the UI label),
country alone and mixed case.
"""

from datetime import date

import pytest

from app.agents import static_results as s
from app.db.seed_airports import AIRPORTS
from app.schemas.request import TravelSearchRequest

# Table keys that are spelling variants of the same country.
_SAME_COUNTRY = {"czech republic": "czechia"}

# How the airport seed (and therefore the IATA rewrite / UI label) names
# countries whose table key is an abbreviation.
_DISPLAY_NAME = {
    "uk": "United Kingdom",
    "usa": "United States",
    "uae": "United Arab Emirates",
    "czechia": "Czech Republic",
}


def _canon(key: str | None) -> str | None:
    return _SAME_COUNTRY.get(key, key) if key else None


_DEST_TABLES = {
    "score": s._DESTINATION_SCORES,
    "emergency": s._EMERGENCY_NUMBERS,
    "sim": s._LOCAL_SIMS,
    "tips": s._DESTINATION_TIPS,
    "getting_around": s._GETTING_AROUND_TABLE,
    "currency": s._DEST_CURRENCY,
    "forex": s._FOREX_TABLE,
}
_VISA_DESTS = {d for _, d in s._VISA_TABLE}
_ALL_KEYS = {_canon(k) for t in _DEST_TABLES.values() for k in t} | _VISA_DESTS
_COUNTRY_BY_NAME = {
    **{k: k for k in _ALL_KEYS},
    **{v.lower(): k for k, v in _DISPLAY_NAME.items()},
}


def _req(destination: str, nationality: str = "American") -> TravelSearchRequest:
    # model_construct: skip the IATA-resolving validator, which would look up
    # three-letter inputs like "USA" in the airports DB / on the web.
    return TravelSearchRequest.model_construct(
        origin="New York",
        destination=destination,
        departure_date=date(2026, 5, 1),
        return_date=date(2026, 5, 8),
        nationality=nationality,
        budget_usd=3000,
    )


def _key_of(table: dict, value) -> str:
    return next(k for k, v in table.items() if v is value)


def _first_row_key(table: dict, items: list) -> str | None:
    for key, rows in table.items():
        if rows and any(item == rows[0] for item in items):
            return key
    return None


def lookups(destination: str, nationality: str = "American") -> dict:
    """Which table row each public lookup used for this destination."""
    r = _req(destination, nationality)
    visa = s.get_static_visa(r)
    score = s.get_confidence_score(r)
    emergency = s.get_static_emergency_numbers(destination)
    forex = s.get_static_forex(r)
    rows = {
        "visa": None
        if visa is None
        else _key_of(s._VISA_TABLE, visa["requirement"])[1],
        "score": None
        if score is None
        else next(
            k
            for k, d in s._DESTINATION_SCORES.items()
            if d["notes"]["safety"] == score["sub_scores"]["safety"]["note"]
            and d["avg_daily_cost_usd"] == s.get_destination_daily_cost(r)
        ),
        "emergency": None
        if emergency is None
        else _key_of(s._EMERGENCY_NUMBERS, emergency),
        "sim": _first_row_key(s._LOCAL_SIMS, s.get_static_sim(r)["plans"]),
        "tips": _first_row_key(s._DESTINATION_TIPS, s.get_static_tips(r)["tips"]),
        "getting_around": _first_row_key(
            s._GETTING_AROUND_TABLE, s.get_static_getting_around(r)["options"]
        ),
        "currency": None
        if forex is None
        else _key_of(s._DEST_CURRENCY, forex["local_currency"]),
        "forex": None
        if forex is None or "card_acceptance" not in forex
        else next(
            k
            for k, d in s._FOREX_TABLE.items()
            if d["card_acceptance"] is forex["card_acceptance"]
        ),
    }
    return {name: _canon(key) for name, key in rows.items()}


def expected(country: str | None, nationality: str = "american") -> dict:
    """The row each lookup should use for a destination in ``country``."""
    out = {}
    for name, table in _DEST_TABLES.items():
        keys = {_canon(k) for k in table}
        out[name] = country if country in keys else None
    out["visa"] = country if (nationality, country) in s._VISA_TABLE else None
    return out


def _realistic_inputs() -> list[tuple[str, str | None]]:
    """(destination string, country it names) pairs, deduplicated."""
    pairs: dict[str, str | None] = {}
    for key in sorted(_ALL_KEYS):
        name = _DISPLAY_NAME.get(key, key.title())
        for form in (key, key.title(), key.upper(), name):
            pairs.setdefault(form, key)
    for city, country in sorted(s._CITY_TO_COUNTRY.items()):
        name = _DISPLAY_NAME.get(country, country.title())
        pairs.setdefault(city.title(), country)
        pairs.setdefault(city.upper(), country)
        pairs.setdefault(f"{city.title()}, {name}", country)
    seen_iata_cities: set[str] = set()
    for iata, _icao, _name, city, country, *_ in AIRPORTS:
        target = _COUNTRY_BY_NAME.get(country.lower())
        pairs.setdefault(f"{city}, {country}", target)
        if city not in seen_iata_cities:
            seen_iata_cities.add(city)
            pairs.setdefault(f"{iata} — {city}, {country}", target)
    return sorted(pairs.items(), key=lambda p: p[0])


REALISTIC = _realistic_inputs()


@pytest.mark.parametrize(("destination", "country"), REALISTIC)
def test_realistic_destination_uses_its_own_row(destination, country):
    assert lookups(destination) == expected(country)


@pytest.mark.parametrize(
    ("destination", "country"),
    [
        ("tOkYo", "japan"),
        ("  Barcelona ,  Spain ", "spain"),
        ("Tokyo Japan", "japan"),
        ("Paris France", "france"),
        ("Miami, FL", "usa"),
        ("Honolulu, Hawaii", "usa"),
        ("Hawaii", "usa"),
        ("Machu Picchu", "peru"),
        ("New York City", "usa"),
        ("Korea", "south korea"),
        ("England", "uk"),
        ("Great Britain", "uk"),
        ("The Netherlands", "netherlands"),
        ("United States of America", "usa"),
        ("São Paulo, Brazil", "brazil"),
        ("SGN — Ho Chi Minh City, Vietnam", "vietnam"),
    ],
)
def test_common_variants_resolve(destination, country):
    assert lookups(destination) == expected(country)


# ── Inputs the old substring matching resolved to the wrong row ─────────────


@pytest.mark.parametrize(
    ("destination", "country"),
    [
        # "india" is a substring of "indiana(polis)"
        ("Indianapolis, United States", "usa"),
        ("Indiana", None),
        # "uk" is a substring of "ukraine" / "phuket"
        ("Kiev, Ukraine", None),
        ("Ukraine", None),
        ("Phuket", "thailand"),
        # a known city name in another country: the stated country wins
        ("Cartagena, Spain", "spain"),
        # a territory listed as its own country is not its parent country
        ("Hong Kong, China", "hong kong"),
        # "niger" ⊂ "nigeria", "oman" ⊂ "romania", "chile" ⊂ "chilean"
        ("Lagos, Nigeria", None),
        ("Bucharest, Romania", None),
        # destination text that is merely a substring of a key
        ("a", None),
        ("Ind", None),
        ("Can", None),
        ("Port of Spain, Trinidad and Tobago", None),
    ],
)
def test_substring_lookalikes_do_not_match(destination, country):
    assert lookups(destination) == expected(country)


# ── Nationality ──────────────────────────────────────────────────────────────


_VISA_NATS = sorted({n for n, _ in s._VISA_TABLE})


@pytest.mark.parametrize("nat", _VISA_NATS)
@pytest.mark.parametrize("form", [str.title, str.upper, lambda n: f"  {n} "])
def test_visa_nationality_exact_forms(nat, form):
    for dest in sorted(_VISA_DESTS):
        name = _DISPLAY_NAME.get(dest, dest.title())
        got = lookups(name, form(nat))["visa"]
        assert got == (dest if (nat, dest) in s._VISA_TABLE else None), (nat, dest)


@pytest.mark.parametrize(
    "nationality",
    [
        "American Samoan",  # contains "american"
        "British Virgin Islander",  # contains "british"
        "American Indian",  # contains both "american" and "indian"
        "Germany",  # contains "german"
        "Anglo-Indian",
    ],
)
def test_visa_nationality_no_substring_match(nationality):
    for dest in ("Japan", "Tokyo, Japan", "France", "Thailand", "USA", "Seattle"):
        assert s.get_static_visa(_req(dest, nationality)) is None


def test_visa_row_helper_matches_get_static_visa():
    """Discovery's visa override uses the same exact lookup."""
    assert s.find_visa_row("Indian", "Kyoto") is s._VISA_TABLE[("indian", "japan")]
    assert s.find_visa_row("Indian", "Indianapolis") is None
    assert s.find_visa_row("American Samoan", "Japan") is None


# ── normalise_place ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "city", "country"),
    [
        ("Tokyo", "tokyo", None),
        ("Barcelona, Spain", "barcelona", "spain"),
        ("BCN — Barcelona, Spain", "barcelona", "spain"),
        ("JFK - New York, United States", "new york", "usa"),
        ("Japan", None, "japan"),
        ("United Kingdom", None, "uk"),
        ("Hong Kong, Hong Kong", None, "hong kong"),
        ("Kyoto, Kansai, Japan", "kyoto", "japan"),
    ],
)
def test_normalise_place(raw, city, country):
    place = s.normalise_place(raw)
    assert place["city"] == city
    assert place["country"] == country
    assert isinstance(place["tokens"], set)


def test_single_city_to_country_map():
    """The two duplicated maps were merged into one module-level map."""
    assert s._CITY_TO_COUNTRY["tokyo"] == "japan"
    assert s._CITY_TO_COUNTRY["dubrovnik"] == "croatia"


# ── City-map fallback when the stated "country" isn't a country ─────────────


@pytest.mark.parametrize(
    ("destination", "country"),
    [
        ("Paris, Texas", None),  # US state that disagrees with the city map
        ("Paris, TX", None),
        ("Miami, FL", "usa"),
        ("Miami, Florida", "usa"),
        ("Honolulu, Hawaii", "usa"),
        ("Paris, France", "france"),
        ("Paris, FR", "france"),  # other short codes fall back to the map
        ("Toronto, ON", "canada"),
        ("Kyoto, Kansai", "japan"),
        ("Barcelona, Catalonia", "spain"),
        ("Barcelona, Europe", None),  # not a code, state or region
        ("Tokyo, Somewhere", None),
    ],
)
def test_city_map_fallback_only_for_codes_states_and_regions(destination, country):
    assert lookups(destination) == expected(country)


# ── Currency lookups (static forex + forex agent) ────────────────────────────


def test_forex_agent_destination_currency_is_exact():
    from app.agents.forex_agent import _resolve_destination_currency

    assert _resolve_destination_currency("Busan")[0] == "KRW"  # "usa" ⊂ "busan"
    assert _resolve_destination_currency("Busan, South Korea")[0] == "KRW"
    assert _resolve_destination_currency("Lusaka, Zambia") is None
    assert _resolve_destination_currency("Indianapolis, United States")[0] == "USD"
    assert _resolve_destination_currency("Colombo")[0] == "LKR"
    assert _resolve_destination_currency("PRG — Prague, Czech Republic")[0] == "CZK"


@pytest.mark.parametrize(
    "resolve",
    [
        "app.agents.forex_agent._get_home_currency",
        "app.agents.static_results._get_nat_currency",
    ],
)
def test_home_currency_nationality_is_exact(resolve):
    import importlib

    module, name = resolve.rsplit(".", 1)
    fn = getattr(importlib.import_module(module), name)
    assert fn("American")[0] == "USD"
    assert fn("  american ")[0] == "USD"
    assert fn("South Korean")[0] == "KRW"
    assert fn("North Korean") is None  # "korean" ⊂ "north korean"
    assert fn("American Samoan") is None
    assert fn("Indian")[0] == "INR"


def test_static_forex_busan_is_not_usd():
    fx = s.get_static_forex(_req("Busan"))
    assert fx["local_currency"]["code"] == "KRW"


# ── ISO 3166 alpha-2 country codes ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("destination", "country"),
    [
        # ISO codes that are also US state codes (DE, CA, ID, IN)
        ("Berlin, DE", "germany"),
        ("Toronto, CA", "canada"),
        ("Bali, ID", "indonesia"),
        ("Delhi, IN", "india"),
        ("Paris, FR", "france"),
        ("Tokyo, JP", "japan"),
        ("London, GB", "uk"),
        ("Dubai, AE", "uae"),
        ("Miami, FL", "usa"),
        ("Los Angeles, CA", "usa"),  # California agrees with the city map
        ("Paris, TX", None),
        ("Paris, Texas", None),
        ("Paris, DE", None),  # ambiguous code; neither reading is France
        ("Paris, GA", None),
        # a known city in another country, named by a non-state ISO code
        ("Cartagena, ES", "spain"),
        ("Cartagena, CO", "colombia"),
        # US cities whose state code is also an ISO country code
        ("Denver, CO", "usa"),
        ("Springfield, IL", "usa"),
        ("Wilmington, DE", "usa"),
        # unknown city: an ISO-only code names its country, a state-only code
        # the USA, a code that is both is ambiguous
        ("Trondheim, NO", "norway"),
        ("Hiroshima, JP", "japan"),
        ("Austin, TX", "usa"),
        ("Smalltown, CO", None),
        ("Leipzig, DE", None),
        ("Leipzig, Germany", "germany"),
        ("Nowhere, ZZ", None),
        ("Paris, US", None),  # US reads as the USA, the city map says France
        # regional codes beyond US states (Canada, Australia, Brazil)
        ("Perth, WA", "australia"),
        ("Seattle, WA", "usa"),
        ("Toronto, ON", "canada"),
        ("Fremantle, WA", None),  # Washington or Western Australia
        ("Charlottetown, PE", None),  # Peru, PEI or Pernambuco
        ("St. John's, NL", None),  # Netherlands or Newfoundland
        ("Belém, PA", "brazil"),
        ("Florianópolis, SC", "brazil"),
        ("Smalltown, PA", None),  # Pennsylvania or Pará
        ("Sydney, NSW", "australia"),
    ],
)
def test_iso_country_codes(destination, country):
    assert lookups(destination) == expected(country)


def test_every_table_country_has_an_iso_code():
    assert set(s._ISO_COUNTRY.values()) == set(s._known_countries())
    assert all(len(code) == 2 for code in s._ISO_COUNTRY)


def test_us_state_module_is_shared():
    from app.core.places import _US_STATES

    assert s._US_STATES is _US_STATES
    assert _US_STATES["tx"] == "texas"


def test_region_codes_table():
    from app.core.places import _REGION_CODES

    assert _REGION_CODES["wa"] == {"US", "AU"}
    assert _REGION_CODES["pe"] == {"CA", "BR"}
    assert _REGION_CODES["nsw"] == {"AU"}
    assert sum("BR" in c for c in _REGION_CODES.values()) == 27
