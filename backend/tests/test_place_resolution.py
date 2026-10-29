"""resolve_place: any typed place → one ranked GeoNames place (or a curated
island / destination) with its scheduled airports, from the seeded session DB.
"""

import csv

import pytest

from app.core.places import COUNTRY_ALIASES, DESTINATION_AIRPORTS, ISLAND_AIRPORTS
from app.db import places_db
from app.db.database import get_connection
from app.db.places_db import resolve, resolve_place
from app.db.seed_airports import PLACE_DATA_DIR


@pytest.fixture(autouse=True)
def seeded_db(client):
    """The session client seeds the place data on startup."""


@pytest.mark.parametrize(
    ("text", "country", "first_airports"),
    [
        ("Milan", "IT", {"LIN", "MXP", "BGY"}),
        ("Milano", "IT", {"LIN", "MXP", "BGY"}),
        ("München", "DE", {"MUC"}),
        ("Munich, Bavaria", "DE", {"MUC"}),
        ("Lisboa", "PT", {"LIS"}),
        ("Bombay", "IN", {"BOM"}),
        ("Saigon", "VN", {"SGN"}),
        ("Chisinau", "MD", {"RMO"}),
        ("Chișinău", "MD", {"RMO"}),
        ("Phnom Penh", "KH", {"KTI"}),
        ("Siem Reap", "KH", {"SAI"}),
        ("Brussels", "BE", {"BRU"}),
        ("Caracas", "VE", {"CCS"}),
        ("Ubud", "ID", {"DPS"}),
        ("London, ON", "CA", {"YXU"}),
        ("London, Ontario", "CA", {"YXU"}),
        ("Sydney, Nova Scotia", "CA", {"YQY"}),
        ("Portland", "US", {"PDX"}),  # dominance: Oregon over Maine
        ("Portland, ME", "US", {"PWM"}),
        ("Birmingham", "GB", {"BHX"}),
        ("Birmingham, AL", "US", {"BHM"}),
        ("Valencia, Spain", "ES", {"VLC"}),
        ("Perth, WA", "AU", {"PER"}),
        ("Seattle, WA", "US", {"SEA"}),
        ("Kansas City", "US", {"MCI"}),  # MO and KS share MCI
        ("Kansas City, KS", "US", {"MCI"}),
        ("St Louis", "US", {"STL"}),
        ("Toronto, CA", "CA", {"YYZ"}),
        ("Springfield, IL", "US", {"SPI"}),
        ("Basel", "CH", {"BSL"}),
        ("Basel, Switzerland", "CH", {"BSL"}),
        ("Basel, CH", "CH", {"BSL"}),
        ("BER — Berlin, Germany", "DE", {"BER"}),
        ("Denver, CO", "US", {"DEN"}),
        ("Atlanta, Georgia", "US", {"ATL"}),  # US state name, not the country
        ("Tbilisi, Georgia", "GE", {"TBS"}),
        ("Columbus, GA", "US", {"CSG"}),
    ],
)
def test_resolves_to_place_and_airports(text, country, first_airports):
    place = resolve_place(text)
    assert place is not None, text
    assert place.country_code == country
    assert place.airports and place.airports[0] in first_airports, place.airports


@pytest.mark.parametrize(
    ("text", "country"),
    [
        ("St Petersburg", "RU"),  # St/Saint spellings pooled before dominance
        ("Saint Petersburg", "RU"),
        ("Zermatt", "CH"),
        ("Interlaken", "CH"),
        ("Interlaken, Switzerland", "CH"),
        ("Kyoto", "JP"),
        ("Venice", "IT"),
        ("Hallstatt", "AT"),
        ("Zermatt, Valais", "CH"),  # admin1 name of any country
        ("Paris, Texas", "US"),
    ],
)
def test_resolves_to_country(text, country):
    place = resolve_place(text)
    assert place is not None and place.country_code == country


@pytest.mark.parametrize(
    "text",
    ["Valencia", "San Jose", "Springfield", "Odessa", "Newcastle"],
)
def test_ambiguous_names_resolve_to_nothing(text):
    result = resolve(text)
    assert result.place is None and result.ambiguous


@pytest.mark.parametrize(
    "text", ["", "   ", "Xyzzyville", "Berlin, Japan", "Smalltown, CO", ", ,"]
)
def test_unknown_or_contradicted_places_resolve_to_nothing(text):
    assert resolve_place(text) is None


# ── Alternate names compete at a calibrated penalty ─────────────────────────


@pytest.mark.parametrize(
    ("text", "country"),
    [
        ("Cancun", "MX"),  # not Changchun (an alternate name of it)
        ("Venice", "IT"),  # not Dayton (alternate) or Venice, Florida
        ("Cologne", "DE"),  # Köln by its alternate name
        ("Bruges", "BE"),
        ("Mecca", "SA"),
        ("Nara", "JP"),
        ("Calcutta", "IN"),
        ("Madras", "IN"),
    ],
)
def test_alternate_names_resolve_famous_places(text, country):
    assert resolve_place(text).country_code == country


def test_alt_name_penalty_is_the_calibrated_value():
    assert places_db.ALT_NAME_PENALTY == 0.006
    assert places_db.DOMINANCE == 3.0


@pytest.fixture
def extra_place():
    ids: list[int] = []

    def add(gid, name, cc, population, score, airports, names):
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO places VALUES (?, ?, ?, '', ?, ?, 0, 0, ?)",
                (gid, name, cc, population, score, airports),
            )
            conn.executemany(
                "INSERT INTO place_names VALUES (?, ?, ?)",
                [(n, gid, tier) for n, tier in names],
            )
        ids.append(gid)

    yield add
    with get_connection() as conn:
        for gid in ids:
            conn.execute("DELETE FROM places WHERE geonameid = ?", (gid,))
            conn.execute("DELETE FROM place_names WHERE geonameid = ?", (gid,))


def test_population_zero_places_never_resolve(extra_place):
    extra_place(990000001, "Zeroville", "DE", 0, 10**12, "BER", [("zeroville", 0)])
    assert resolve_place("Zeroville") is None
    extra_place(990000002, "Zeroville", "FR", 1500, 10, "CDG", [("zeroville", 0)])
    assert resolve_place("Zeroville").country_code == "FR"  # the 0 is no rival


def test_alternate_match_competes_at_the_penalty(extra_place):
    extra_place(990000003, "Altburg", "DE", 200_000, 2000, "BER", [("altname", 1)])
    extra_place(990000004, "Altname", "FR", 5000, 20, "CDG", [("altname", 0)])
    # 2000 × 0.006 = 12 against 20: within 3× → ambiguous
    assert resolve("Altname").ambiguous
    extra_place(990000005, "Bigalt", "IT", 200_000, 10**6, "FCO", [("altname", 1)])
    assert resolve_place("Altname").country_code == "IT"


# ── Countries, divisions, curated islands and destinations ─────────────────


@pytest.mark.parametrize(
    ("text", "country", "airport"),
    [
        ("Japan", "JP", "HND"),
        ("Georgia", "GE", "TBS"),  # the country when typed alone
        ("Italy", "IT", "FCO"),
        ("Bavaria", "DE", "MUC"),  # a division alone → its dominant place
        ("England", "GB", "LHR"),
    ],
)
def test_country_and_division_names(text, country, airport):
    place = resolve_place(text)
    assert place.country_code == country
    assert airport in place.airports


@pytest.mark.parametrize(
    ("text", "country", "first"),
    [
        ("Sicily", "IT", "CTA"),
        ("Bali", "ID", "DPS"),
        ("Crete", "GR", "HER"),
        ("Mallorca", "ES", "PMI"),
        ("Majorca", "ES", "PMI"),
        ("Galápagos", "EC", "GPS"),
        ("Big Island", "US", "KOA"),
        ("Machu Picchu", "PE", "CUZ"),
        ("Petra", "JO", "AQJ"),
        ("Kyoto", "JP", "KIX"),
        ("Kyoto, Japan", "JP", "KIX"),
        ("Banff", "CA", "YYC"),
    ],
)
def test_islands_and_destinations_come_first(text, country, first):
    place = resolve_place(text)
    assert (place.country_code, place.airports[0]) == (country, first)


def test_destination_hint_yields_to_another_stated_country():
    place = resolve_place("Petra, Spain")  # the Mallorca town, not Jordan
    assert place is None or place.country_code == "ES"


@pytest.fixture(scope="module")
def dataset_airports():
    with open(PLACE_DATA_DIR / "airports.csv", newline="", encoding="utf-8") as f:
        return {r["iata"]: r for r in csv.DictReader(f)}


@pytest.mark.parametrize("table", [ISLAND_AIRPORTS, DESTINATION_AIRPORTS])
def test_hint_airports_are_scheduled_in_the_data(table, dataset_airports):
    for name, (country, codes) in table.items():
        assert name == name.lower().strip(), name
        assert len(country) == 2 and codes, name
        for code in codes:
            assert dataset_airports[code]["scheduled"] == "1", (name, code)


def test_hint_tables_are_large_enough():
    assert len(ISLAND_AIRPORTS) >= 40
    assert len(DESTINATION_AIRPORTS) >= 40


# ── One alias map ────────────────────────────────────────────────────────────


def test_country_aliases_are_shared():
    import app.db.database as database
    from app.agents import static_results

    assert not hasattr(database, "_COUNTRY_CODE_ALIASES")
    for name, iso in COUNTRY_ALIASES.items():
        assert places_db.stated_countries(name) == {iso}
        key = static_results._ISO_COUNTRY.get(iso.lower())
        if key and key != name:
            assert static_results._COUNTRY_ALIASES[name] == key


def test_resolution_uses_at_most_two_queries():
    statements: list[str] = []
    with get_connection() as conn:
        conn.set_trace_callback(statements.append)
        assert resolve_place("Munich, Bavaria", conn).airports[0] == "MUC"
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 2


# ── Final review: regions, saint countries, alternates, hints ─────────────


@pytest.mark.parametrize(
    ("text", "country", "airports"),
    [
        ("Florida", "US", {"MCO", "MIA", "TPA", "FLL", "JAX"}),  # not Florida, UY
        ("Florida, USA", "US", {"MCO", "MIA", "TPA", "FLL", "JAX"}),
        ("Andalusia", "ES", {"AGP", "SVQ", "XRY"}),  # not Andalusia, AL
        ("Normandy", "FR", {"CFR", "DOL", "URO", "LEH"}),  # not Normandy, MO
        ("Scotland", "GB", {"EDI", "GLA", "PIK"}),  # its own top place
        ("Wales", "GB", {"CWL", "BRS"}),
        ("Northern Ireland", "GB", {"BFS", "BHD"}),
    ],
)
def test_division_names_are_candidates(text, country, airports):
    place = resolve_place(text)
    assert place is not None and place.country_code == country, place
    assert place.airports and place.airports[0] in airports, place.airports


@pytest.mark.parametrize(
    ("text", "country"),
    [
        ("St Lucia", "LC"),
        ("Saint Lucia", "LC"),
        ("St Vincent", "VC"),
        ("St Kitts", "KN"),
        ("St Barts", "BL"),
        ("St Barths", "BL"),
        ("St Maarten", "SX"),
        ("St. Lucia", "LC"),
    ],
)
def test_saint_forms_of_countries(text, country):
    place = resolve_place(text)
    assert place is not None and place.country_code == country, place


@pytest.mark.parametrize(
    ("text", "country", "first"),
    [
        ("Rio", "BR", {"GIG", "SDU"}),
        ("Rio, Brazil", "BR", {"GIG", "SDU"}),
        ("Port Douglas", "AU", {"CNS"}),  # not Douglas, Isle of Man (26k)
        ("Dili", "TL", {"DIL"}),  # a capital beats Delhi's alternate "dili"
        ("Lucerne", "CH", {"ZRH"}),
    ],
)
def test_alternate_name_rules(text, country, first):
    place = resolve_place(text)
    assert place is not None and place.country_code == country, place
    assert place.airports[0] in first, place.airports


def test_small_places_do_not_compete_by_alternate_name(extra_place):
    extra_place(990000011, "Bigalt", "DE", 90_000, 10**12, "BER", [("smallalt", 1)])
    extra_place(990000012, "Smallalt", "FR", 2_000, 10, "CDG", [("smallalt", 0)])
    assert resolve_place("Smallalt").country_code == "FR"


@pytest.mark.parametrize(
    ("text", "country", "first"),
    [
        ("Elba", "IT", "EBA"),
        ("Elba, Italy", "IT", "EBA"),
        ("Gozo", "MT", "MLA"),
        ("Formentera", "ES", "IBZ"),
        ("Siargao", "PH", "IAO"),
        ("Koh Lanta", "TH", "KBV"),
        ("Nusa Penida", "ID", "DPS"),
        ("Gili Islands", "ID", "LOP"),
        ("Martha's Vineyard", "US", "MVY"),
        ("Jackson Hole", "US", "JAC"),
        ("Los Cabos", "MX", "SJD"),
        ("Cabo San Lucas", "MX", "SJD"),
        ("St Moritz", "CH", "ZRH"),
        ("Davos", "CH", "ZRH"),
        ("Park City", "US", "SLC"),
        ("Kona", "US", "KOA"),
    ],
)
def test_final_review_hints(text, country, first):
    place = resolve_place(text)
    assert (place.country_code, place.airports[0]) == (country, first)


def test_fez_is_fes():
    assert resolve_place("Fez").country_code == "MA"


@pytest.mark.parametrize("text", ["Santa Fe"])
def test_cities_named_like_a_division_keep_the_cities(text):
    """Santa Fe, NM vs Santa Fe, AR (both ≥ 100k-class cities): the
    province's top place (Rosario) does not join."""
    assert resolve(text).place is None


def test_mahe_is_the_seychelles_island():
    assert resolve_place("Mahé").country_code == "SC"
