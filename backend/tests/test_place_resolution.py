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


# ── Alternate names: only without an own-name candidate, plus EXONYMS ──────


@pytest.mark.parametrize(
    ("text", "country"),
    [
        ("Cancun", "MX"),  # not Changchun (an alternate name of it)
        ("Venice", "IT"),  # not Dayton (alternate) or Venice, Florida
        ("Cologne", "DE"),  # Köln, by the EXONYMS map
        ("Bruges", "BE"),
        ("Mecca", "SA"),
        ("Nara", "JP"),
        ("Calcutta", "IN"),
        ("Madras", "IN"),
    ],
)
def test_alternate_names_resolve_famous_places(text, country):
    assert resolve_place(text).country_code == country


def test_no_alternate_name_penalty_any_more():
    assert not hasattr(places_db, "ALT_NAME_PENALTY")
    assert not hasattr(places_db, "ALT_MIN_POPULATION")
    assert places_db.DOMINANCE == 3.0


@pytest.fixture
def extra_place():
    ids: list[int] = []

    def add(gid, name, cc, population, score, airports, names, satellite=0, at=(0, 0)):
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO places (geonameid, name, country_code, admin1,"
                " population, score, lat, lng, airports, satellite)"
                " VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?)",
                (gid, name, cc, population, score, *at, airports, satellite),
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
    extra_place(990000002, "Zeroville", "FR", 6000, 10, "CDG", [("zeroville", 0)])
    assert resolve_place("Zeroville").country_code == "FR"  # the 0 is no rival


def test_alternates_count_only_without_an_own_name_candidate(extra_place):
    extra_place(990000003, "Altburg", "DE", 200_000, 10**9, "BER", [("altname", 1)])
    extra_place(990000004, "Altname", "FR", 20_000, 20, "CDG", [("altname", 0)])
    assert resolve_place("Altname").country_code == "FR"  # own name wins
    extra_place(990000005, "Onlyalt", "IT", 50_000, 10**6, "FCO", [("altonly", 1)])
    assert resolve_place("Altonly").country_code == "IT"  # no own name: alt


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


def test_r3_a_far_bigger_alternate_joins_a_small_own_name(extra_place):
    extra_place(990000011, "Bigalt", "DE", 200_000, 10**12, "BER", [("smallalt", 1)])
    extra_place(990000012, "Smallalt", "FR", 6_000, 10, "CDG", [("smallalt", 0)])
    assert resolve_place("Smallalt").country_code == "DE"  # ≥ 10×, ≥ 150k
    extra_place(990000015, "Midalt", "DE", 90_000, 10**12, "BER", [("smallish", 1)])
    extra_place(990000016, "Smallish", "FR", 6_000, 10, "CDG", [("smallish", 0)])
    assert resolve_place("Smallish").country_code == "FR"  # 90k: too small
    extra_place(990000013, "Ownbig", "FR", 30_000, 10, "CDG", [("ownbig", 0)])
    extra_place(990000014, "Altbig", "DE", 900_000, 10**12, "BER", [("ownbig", 1)])
    assert resolve_place("Ownbig").country_code == "FR"  # ≥ 20k blocks


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


# ── Final re-review: exonyms, small places, hints, region hints ───────────


@pytest.mark.parametrize(
    ("text", "country", "first"),
    [
        ("Cologne", "DE", {"CGN"}),
        ("Bruges", "BE", {"OST", "BRU"}),
        ("Mecca", "SA", {"JED"}),
        ("Medina", "SA", {"MED"}),
        ("Gerona", "ES", {"GRO"}),
        ("Londonderry", "GB", {"LDY"}),
        ("Calcutta", "IN", {"CCU"}),
        ("Madras", "IN", {"MAA"}),
        ("Peking", "CN", {"PEK", "PKX"}),
        ("Leghorn", "IT", {"PSA"}),
        ("Saragossa", "ES", {"ZAZ"}),
        ("Seville", "ES", {"SVQ"}),
        ("Aix", "FR", {"MRS"}),
        ("Jogja", "ID", {"YIA", "JOG"}),
        ("Olbia", "IT", {"OLB"}),  # own name: Antalya's alternate never competes
        ("Puno", "PE", {"JUL"}),
        ("Hualien", "TW", {"HUN"}),
        ("Turkmenbashi", "TM", {"KRW"}),
        ("Zihuatanejo", "MX", {"ZIH"}),
        ("Port Douglas", "AU", {"CNS"}),
        ("Dili", "TL", {"DIL"}),
    ],
)
def test_exonyms_and_own_names(text, country, first):
    place = resolve_place(text)
    assert place is not None and place.country_code == country, place
    assert place.airports[0] in first, place.airports


@pytest.mark.parametrize("text", ["Odessa", "Smyrna"])
def test_exonyms_marked_ambiguous(text):
    result = resolve(text)
    assert result.place is None and result.ambiguous


def test_every_exonym_points_at_a_seeded_place():
    from app.core.places import EXONYMS

    assert len(EXONYMS) >= 60
    with get_connection() as conn:
        for name, target in EXONYMS.items():
            assert name == name.lower().strip(), name
            if target == "ambiguous":
                continue
            row = conn.execute(
                "SELECT airports FROM places WHERE geonameid = ?", (target,)
            ).fetchone()
            assert row is not None, name


@pytest.mark.parametrize(
    ("text", "result"),
    [
        ("Gap", "FR"),  # Gap, France (fallback links only) dominates Gap, PA
        ("Praslin", "SC"),
        ("Antigua", "AG"),
        ("Turks and Caicos", "TC"),
        ("Ceylon", "LK"),
    ],
)
def test_small_places_and_country_aliases(text, result):
    place = resolve_place(text)
    assert place is not None and place.country_code == result, place


def test_small_place_wins_only_alone(extra_place):
    extra_place(990000021, "Tinytown", "DE", 6_000, 10**7, "BER", [("tinytown", 0)])
    assert resolve_place("Tinytown").country_code == "DE"  # sole candidate
    extra_place(990000022, "Tinytown", "FR", 2_000, 10, "CDG", [("tinytown", 0)])
    assert resolve_place("Tinytown") is None  # < 15k and not alone


@pytest.mark.parametrize(
    ("text", "country", "first"),
    [
        ("Sylt", "DE", "GWT"),
        ("St Thomas", "VI", "STT"),
        ("St John", "VI", "STT"),
        ("St Croix", "VI", "STX"),
        ("Sun Valley", "US", "SUN"),
        ("Yorkshire", "GB", "LBA"),
        ("Cornwall", "GB", "NQY"),
        ("Black Forest", "DE", "FKB"),
        ("Lake District", "GB", "MAN"),
        ("Cotswolds", "GB", "BRS"),
        ("Provence", "FR", "MRS"),
        ("French Riviera", "FR", "NCE"),
        ("Côte d'Azur", "FR", "NCE"),
        ("Amalfi Coast", "IT", "NAP"),
        ("Cinque Terre", "IT", "PSA"),
        ("Algarve", "PT", "FAO"),
        ("Costa del Sol", "ES", "AGP"),
        ("Lake Como", "IT", "MXP"),
        ("Dolomites", "IT", "VCE"),
        ("Scottish Highlands", "GB", "INV"),
        ("Napa", "US", "SFO"),
        ("Nosy Be", "MG", "NOS"),
        ("Isla Margarita", "VE", "PMV"),
        ("Fernando de Noronha", "BR", "FEN"),
        ("Porto Santo", "PT", "PXO"),
        ("Terceira", "PT", "TER"),
        ("Lesbos", "GR", "MJT"),
        ("Bornholm", "DK", "RNN"),
        ("Shetland", "GB", "LSI"),
        ("Grand Cayman", "KY", "GCM"),
        ("Eleuthera", "BS", "ELH"),
        ("Nevis", "KN", "NEV"),
        ("Tortola", "VG", "EIS"),
        ("Ambergris Caye", "BZ", "SPR"),
        ("Huatulco", "MX", "HUX"),
        ("Lanai", "US", "LNY"),
        ("Kangaroo Island", "AU", "KGC"),
        ("Jiuzhaigou", "CN", "JZH"),
        ("AlUla", "SA", "ULH"),
        ("Morzine", "FR", "GVA"),
    ],
)
def test_final_re_review_hints(text, country, first):
    place = resolve_place(text)
    assert (place.country_code, place.airports[0]) == (country, first)


# ── Blind-probe rulings R1–R8 ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "country", "first"),
    [
        ("Sudbury", "CA", "YSB"),  # R1/R3: the Sudbury with an airport
        ("Knock", "IE", "NOC"),  # R1: "Ireland West Airport Knock"
        ("Wagga Wagga", "AU", "WGA"),  # R1/R8: the town is a GeoNames PPLX
        ("Lord Howe Island", "AU", "LDH"),
        ("La Palma", "ES", "SPC"),  # R1: La Palma, CA has no airport of its own
        ("La Gomera", "ES", "GMZ"),
        ("Ixtapa", "MX", "ZIH"),
    ],
)
def test_r1_airport_name_candidates(text, country, first):
    place = resolve_place(text)
    assert place is not None, text
    assert (place.country_code, place.airports[0]) == (country, first)


def test_r2_confidence_floor(extra_place):
    # 1.2k people, only airport ~6,000 km away (fixture places sit at 0,0)
    extra_place(990000031, "Farville", "DE", 1_200, 10**6, "BER", [("farville", 0)])
    assert resolve_place("Farville") is None
    extra_place(990000032, "Nearburg", "DE", 1_200, 10**6, "", [("nearburg", 0)])
    assert resolve_place("Nearburg").country_code == "DE"  # no airport at all


@pytest.mark.parametrize(
    ("text", "country", "first"),
    [
        ("Bâle", "CH", {"BSL"}),  # R3: Basel ≥ 10× the 973-person Bale
        ("Solo", "ID", {"SOC"}),  # R3: Surakarta
        ("Sapa", "VN", {"HAN", "DIN"}),
        ("Dalat", "VN", {"DLI"}),
        ("Sion", "CH", {"SIR", "GVA", "BRN"}),
        ("Olbia", "IT", {"OLB"}),
    ],
)
def test_r3_alternates_and_exonyms(text, country, first):
    place = resolve_place(text)
    assert place is not None and place.country_code == country, place
    assert place.airports[0] in first, place.airports


@pytest.mark.parametrize(
    ("text", "country"),
    [("St. John's, Newfoundland", "CA"), ("George Town, Penang", "MY")],
)
def test_r5_qualifier_prefix_matches_a_division(text, country):
    assert resolve_place(text).country_code == country


@pytest.mark.parametrize(
    ("text", "country", "first"),
    [
        ("Saba", "BQ", "SAB"),
        ("Tanna", "VU", "TAH"),
        ("Wallis", "WF", "WLS"),
        ("Åland", "FI", "MHQ"),
        ("Orkney", "GB", "KOI"),
        ("Java", "ID", "CGK"),
        ("Ilha Grande", "BR", "GIG"),
        ("Monteverde", "CR", "LIR"),
        ("Copper Canyon", "MX", "CUU"),
        ("Mount Rainier", "US", "SEA"),
        ("Cabo", "MX", "SJD"),
        ("El Hierro", "ES", "VDE"),
    ],
)
def test_blind_probe_hints(text, country, first):
    place = resolve_place(text)
    assert (place.country_code, place.airports[0]) == (country, first)


# ── G1–G7: whole-name airports, all countries, readings, affixes ─────────


@pytest.mark.parametrize(
    ("text", "bad"),
    [
        ("Kota", "BKI"),  # not Kota Kinabalu: whole airport names only
        ("Beni", "BEM"),  # not Beni Mellal, Morocco
        ("Kurchatov", "CEK"),
        ("Cape", "CPT"),
        ("Fort", "FLL"),
        ("Lake", "HII"),
    ],
)
def test_g1_airport_name_prefixes_are_not_candidates(text, bad):
    place = resolve_place(text)
    assert place is None or bad not in place.airports, place


def test_g1_kota_is_kota_rajasthan():
    place = resolve_place("Kota")
    assert place.country_code == "IN" and place.population > 500_000


@pytest.mark.parametrize(
    ("text", "first"),
    [
        ("Andorra", {"LEU", "BCN", "TLS"}),
        ("Monaco", {"NCE"}),
        ("Monte Carlo", {"NCE"}),
        ("Liechtenstein", {"ZRH"}),
        ("San Marino", {"RMI", "BLQ"}),
        ("Vatican", {"FCO"}),
    ],
)
def test_g2_countries_without_an_airport(text, first):
    place = resolve_place(text)
    assert place is not None and place.airports[0] in first, place


def test_g2_country_list_is_complete():
    assert places_db.stated_countries("andorra") == {"AD"}
    assert places_db.stated_countries("liechtenstein") == {"LI"}


@pytest.mark.parametrize(
    ("text", "country"),
    [("Ontario, CA", "US"), ("Mumbai, MH", "IN"), ("Panaji, Goa", "IN")],
)
def test_g3_qualifier_readings(text, country):
    assert resolve_place(text).country_code == country


@pytest.mark.parametrize(
    ("text", "first"),
    [
        ("Saint Thomas", "STT"),  # St/Saint variants reach the hint again
        ("Zanzibar Island", "ZNZ"),
        ("Banff National Park", "YYC"),
        ("Isla de Margarita", "PMV"),
        ("Nosy Be Island", "NOS"),
        ("Tokyo city", "HND"),
        ("Mandalay city", "MDL"),
    ],
)
def test_g4_generic_affixes(text, first):
    assert resolve_place(text).airports[0] == first


def test_g4_saint_john_stays_new_brunswick():
    assert resolve_place("Saint John").country_code == "CA"


def test_g4_hints_live_in_a_data_file():
    import json

    from app.core import places

    data = json.loads(places._HINTS_FILE.read_text(encoding="utf-8"))
    assert {"islands", "destinations", "regions", "exonyms", "city_aliases",
            "country_aliases", "saint_exceptions"} <= set(data)  # fmt: skip
    for table in ("islands", "destinations", "regions"):
        for name, (country, codes) in data[table].items():
            assert name == places.fold_place(name) and len(country) == 2 and codes
    assert places.EXONYMS["canton"] == "ambiguous"  # Guangzhou via "Canton, China"
    assert resolve_place("Canton, China").country_code == "CN"


@pytest.mark.parametrize(
    ("text", "country"),
    [
        ("Berlin Germany", "DE"),
        ("Chicago IL", "US"),
        ("Sydney Nova Scotia", "CA"),
        ("Portland Maine", "US"),
        ("Helsinki Finland", "FI"),
        ("Goa India", "IN"),
    ],
)
def test_g6_no_comma_qualifiers(text, country):
    assert resolve_place(text).country_code == country


def test_g6_real_names_with_country_words_are_untouched():
    assert resolve_place("Panama City").country_code == "PA"
    assert resolve_place("Mexico City").country_code == "MX"


# ── Remaining items: country names, satellites, non-town features ──────────


@pytest.mark.parametrize(
    ("segment", "codes"),
    [
        ("deutschland", {"DE"}),
        ("brasil", {"BR"}),
        ("nippon", {"JP"}),
        ("suomi", {"FI"}),
        ("ellada", {"GR"}),
        ("ksa", {"SA"}),  # qualifier-only aliases count as qualifiers
        ("prc", {"CN"}),
        ("rok", {"KR"}),
        ("roc", {"TW"}),
        ("dprk", {"KP"}),
    ],
)
def test_country_names_and_aliases_as_qualifiers(segment, codes):
    assert places_db.stated_countries(segment) == codes


def test_qualifier_only_aliases_stay_airport_codes_alone():
    from app.db.database import code_first

    for code in ("KSA", "PRC", "ROK", "ROC"):
        assert code.lower() not in places_db.country_names()
        assert code_first(code)
    assert not code_first("USA")  # a full alias is never a code


@pytest.mark.parametrize(
    ("text", "country"),
    [
        ("Deutschland", "DE"),
        ("Brasil", "BR"),
        ("España", "ES"),  # not the 2.6k-person España, Philippines
        ("Nippon", "JP"),
        ("Hellas", "GR"),
        ("Berlin, Deutschland", "DE"),
        ("Munich Deutschland", "DE"),
        ("Riyadh, KSA", "SA"),
        ("Beijing PRC", "CN"),
    ],
)
def test_country_names_resolve(text, country):
    assert resolve_place(text).country_code == country


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("Deutschland", "germany"),
        ("Berlin, Deutschland", "germany"),
        ("Madrid, España", "spain"),
        ("Sao Paulo, Brasil", "brazil"),
        ("Tokyo, Nippon", "japan"),
    ],
)
def test_static_tables_read_country_names(text, key):
    from app.agents.static_results import _place_country

    assert _place_country(text) == key


def test_a_big_town_keeps_a_generic_country_name():
    # the generator's guard: "Columbia" (Colombia in some languages) is
    # Columbia, South Carolina; "Nederland" is curated back (native name)
    assert "columbia" not in places_db.country_names()
    assert places_db.country_names()["nederland"] == "NL"


_PIA = (40.66, -89.69)  # a town at PIA flies from its own airport


def test_satellite_leader_yields_to_a_town_with_its_own_airport(extra_place):
    names = [("satburg", 0)]
    extra_place(990000101, "Satburg", "US", 190_000, 4 * 10**8, "PHX", names, 1)
    # named "Peoria" so PIA (Peoria's airport) is named for it
    extra_place(990000102, "Peoria", "US", 115_000, 10**8, "PIA", names, at=_PIA)
    place = resolve_place("Satburg")
    assert place.airports == ("PIA",)  # Peoria: PIA, not Phoenix's PHX


def test_satellite_yields_only_to_a_town_with_its_own_airport(extra_place):
    # Ede: the Nigerian one flies from Ilorin's ILR, 90 km away: no leader
    names = [("satede", 0)]
    extra_place(
        990000107, "Satede", "NL", 67_000, 15 * 10**7, "EIN", names, 1, at=(51.6, 5.6)
    )
    extra_place(990000108, "Satede", "NG", 160_000, 10**8, "ILR", names, at=(7.7, 4.4))
    assert resolve_place("Satede") is None


def test_satellite_keeps_the_lead_over_a_far_smaller_town(extra_place):
    names = [("satville", 0)]
    extra_place(990000103, "Satville", "US", 190_000, 4 * 10**8, "PHX", names, 1)
    extra_place(990000104, "Satville", "US", 15_000, 3 * 10**7, "PIA", names, at=_PIA)
    assert resolve_place("Satville").airports == ("PHX",)  # under 1/10


def test_two_comparable_satellites_stay_ambiguous(extra_place):
    names = [("satton", 0)]
    extra_place(990000105, "Satton", "US", 200_000, 2 * 10**8, "PHX", names, 1)
    extra_place(990000106, "Satton", "US", 190_000, 10**8, "ORD", names, 1)
    assert resolve_place("Satton") is None


@pytest.fixture
def extra_feature():
    ids: list[int] = []

    def add(gid, name, cc, notability, airports, names, at=(-13.0, 132.5), code="PRK"):
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO features (geonameid, name, country_code, admin1,"
                " feature_code, notability, lat, lng, airports)"
                " VALUES (?, ?, ?, '', ?, ?, ?, ?, ?)",
                (gid, name, cc, code, notability, *at, airports),
            )
            conn.executemany(
                "INSERT INTO feature_names VALUES (?, ?, ?)",
                [(n, gid, tier) for n, tier in names],
            )
        ids.append(gid)

    yield add
    with get_connection() as conn:
        for gid in ids:
            conn.execute("DELETE FROM features WHERE geonameid = ?", (gid,))
            conn.execute("DELETE FROM feature_names WHERE geonameid = ?", (gid,))


def test_feature_beats_small_towns_only(extra_place, extra_feature):
    extra_feature(990000201, "Qzparkland Park", "AU", 40, "DRW", [("qzparkland", 0)])
    extra_place(990000202, "Qzparkland", "US", 5_000, 10**7, "ORD", [("qzparkland", 0)])
    place = resolve_place("Qzparkland")
    assert (place.name, place.country_code, place.airports) == (
        "Qzparkland Park",
        "AU",
        ("DRW",),
    )
    assert place.geonameid is None and place.feature
    extra_place(
        990000203, "Qzparkland", "US", 20_000, 10**8, "DEN", [("qzparkland", 0)]
    )
    assert resolve_place("Qzparkland").country_code == "US"  # a real town wins


def test_a_town_at_the_feature_keeps_its_own_answer(extra_place, extra_feature):
    # Paros: the island's town and its airport, not the island's far hubs
    extra_feature(990000208, "Qzisle", "GR", 40, "ATH", [("qzisle", 0)], at=(37, 25))
    extra_place(
        990000209, "Qzisle", "GR", 3_000, 10**6, "PAS", [("qzisle", 0)], at=(37.1, 25.1)
    )
    assert resolve_place("Qzisle").airports == ("PAS",)


def test_feature_respects_a_stated_country(extra_feature):
    extra_feature(990000204, "Featurepeak", "NP", 60, "KTM", [("featurepeak", 0)])
    assert resolve_place("Featurepeak, Nepal").airports == ("KTM",)
    assert resolve_place("Featurepeak, Peru") is None


def test_comparable_features_abroad_are_ambiguous(extra_feature):
    extra_feature(990000205, "Twinlake", "US", 30, "SEA", [("twinlake", 0)])
    extra_feature(990000206, "Twinlake", "CA", 25, "YVR", [("twinlake", 0)])
    assert resolve_place("Twinlake") is None
    extra_feature(990000207, "Twinlake", "US", 200, "BOS", [("twinlake", 0)])
    assert resolve_place("Twinlake").airports == ("BOS",)


@pytest.mark.parametrize(
    ("text", "country", "first"),
    [
        ("Kakadu", "AU", {"DRW"}),
        ("Arches National Park", "US", {"CNY", "GJT"}),
        ("Everest", "NP", {"KTM", "LUA"}),
        ("Lake Tahoe", "US", {"RNO"}),
        ("Matterhorn", "CH", {"GVA", "ZRH"}),
    ],
)
def test_committed_features_resolve(text, country, first):
    place = resolve_place(text)
    assert place.country_code == country and place.airports[0] in first


def test_feature_country_for_the_static_tables():
    from app.agents.static_results import _place_country

    assert _place_country("Kakadu") == "australia"


def test_autocomplete_suggests_features_after_towns():
    from app.db.database import search_airports

    assert search_airports("kakadu")[0]["iata_code"] == "DRW"
    # a real town keeps the lead: no feature padding for "london"
    london = [r["iata_code"] for r in search_airports("london")]
    assert london[0] == "LHR" or "LHR" in london[:3]


@pytest.mark.parametrize(
    ("text", "first"),
    [
        ("Paros", {"PAS"}),
        ("Naxos", {"JNX"}),
        ("Lefkada", {"PVK"}),
        ("Borneo", {"BKI", "KCH"}),
        ("Blue Mountains", {"SYD", "WSI"}),  # the City of Blue Mountains, NSW
        ("Ede", None),
        ("Concord", None),
        ("Newport", {"BRS", "CWL"}),
    ],
)
def test_feature_and_satellite_regressions(text, first):
    place = resolve_place(text)
    if first is None:
        assert place is None
    else:
        assert place.airports[0] in first


@pytest.mark.parametrize(
    ("text", "country"),
    [("Nederland", "NL"), ("Palestine", "PS"), ("Eire", "IE")],
)
def test_native_country_names_beat_small_namesakes(text, country):
    # Nederland, Texas (17k) and Palestine, Texas (18k) blocked these in the
    # generator's collision guard; curated aliases restore the country
    assert COUNTRY_ALIASES[fold_place_name(text)] == country
    assert resolve_place(text).country_code == country


def fold_place_name(text):
    from app.core.places import fold_place

    return fold_place(text)


@pytest.mark.parametrize(
    ("text", "first"),
    [
        ("Lake Garda", {"VRN"}),
        ("Lago di Garda", {"VRN"}),
        ("Sardegna", {"CAG", "OLB", "AHO"}),
    ],
)
def test_lake_garda_and_sardegna_hints(text, first):
    place = resolve_place(text)
    assert place.country_code == "IT" and place.airports[0] in first


def test_ambiguous_features_with_only_small_towns_give_none():
    # Mount Olympus: Cyprus and Greece (and a 6.7k Utah town) → no guess
    assert resolve_place("Mount Olympus") is None


@pytest.mark.parametrize("text", ["Eretria", "Coria", "Grenade", "Cameron"])
def test_colliding_country_names_are_qualifiers_only(text):
    from app.core.places import fold_place

    assert fold_place(text) not in places_db.country_names()
    place = resolve_place(text)
    assert place is None or place.country_code not in {"ER", "KR", "GD", "CM"}


def test_colliding_country_names_still_qualify():
    assert places_db.stated_countries("eretria") == {"ER"}


def test_a_contested_district_name_gives_none_not_a_town(extra_place, extra_feature):
    extra_feature(
        990000301, "Qzcentro", "BR", 12, "GRU", [("qzcentro", 2)], code="PPLX"
    )
    extra_place(990000302, "Qzcentro", "PT", 2_000, 10**6, "LIS", [("qzcentro", 0)])
    assert resolve("Qzcentro").place is None
    assert resolve("Qzcentro").ambiguous


@pytest.mark.parametrize(
    ("text", "first"),
    [
        ("Vila", "VLI"),  # Port Vila's alternate name blocks the Albanian peak
        ("Tongren", "TEN"),  # Guizhou's own Tongren Fenghuang airport
        ("Newport", "BRS"),  # Wales: Newport, RI is far smaller
    ],
)
def test_alternate_towns_and_own_airport_namesakes(text, first):
    from app.db.database import lookup_city_iata

    assert lookup_city_iata(text).split(",")[0] == first
