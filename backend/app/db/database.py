import csv
import functools
import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.places import (
    CITY_ALIASES,
    CODE_PREFIX_RE,
    NEVER_LINK,
    fold_place,
    saint_variants,
    stated_region,
)
from .airport_regions import airport_regions

if TYPE_CHECKING:
    from .places_db import Place

logger = logging.getLogger(__name__)


def _db_path() -> Path:
    from ..core.config import settings

    p = Path(settings.data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / "airports.db"


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """A connection to the app DB: commits when the block succeeds, rolls
    back when it raises, and is always closed."""
    conn = sqlite3.connect(str(_db_path()))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added to ``airports`` after the first release; existing DBs gain
# them in place (web-saved rows default to scheduled).
_AIRPORT_MIGRATIONS = {
    "region": "TEXT",
    "type_rank": "INTEGER",
    "scheduled": "INTEGER DEFAULT 1",
}


def create_tables():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS airports (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                iata_code    TEXT UNIQUE NOT NULL,
                icao_code    TEXT,
                name         TEXT NOT NULL,
                city         TEXT NOT NULL,
                country      TEXT NOT NULL,
                country_code TEXT,
                latitude     REAL,
                longitude    REAL
            );
            CREATE INDEX IF NOT EXISTS idx_airports_iata    ON airports(iata_code);
            CREATE INDEX IF NOT EXISTS idx_airports_city    ON airports(city COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_airports_country ON airports(country_code);

            CREATE TABLE IF NOT EXISTS nationalities (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                nationality  TEXT UNIQUE NOT NULL,
                country      TEXT NOT NULL,
                country_code TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_nationalities_name    ON nationalities(nationality COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_nationalities_country ON nationalities(country COLLATE NOCASE);

            -- GeoNames places (cities1000) and the airports each one links to
            -- (space-separated IATA codes, best first); see app/db/data/README.md
            CREATE TABLE IF NOT EXISTS places (
                geonameid    INTEGER PRIMARY KEY,
                name         TEXT NOT NULL,
                country_code TEXT NOT NULL,
                admin1       TEXT,
                population   INTEGER,
                score        INTEGER,
                lat          REAL,
                lng          REAL,
                airports     TEXT,
                satellite    INTEGER NOT NULL DEFAULT 0
            );
            -- Folded place names: tier 0 = the place's own name, 1 = alternate
            CREATE TABLE IF NOT EXISTS place_names (
                name_folded TEXT NOT NULL,
                geonameid   INTEGER NOT NULL,
                tier        INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_place_names_folded
                ON place_names(name_folded);
            -- GeoNames first-level divisions, code "US.OR", "DE.02", "GB.ENG"
            CREATE TABLE IF NOT EXISTS admin1 (
                code        TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                folded_name TEXT NOT NULL
            );
            -- GeoNames non-town features (islands, parks, mountains…) and
            -- their airports; feature_names as place_names
            CREATE TABLE IF NOT EXISTS features (
                geonameid    INTEGER PRIMARY KEY,
                name         TEXT NOT NULL,
                country_code TEXT NOT NULL,
                admin1       TEXT,
                feature_code TEXT NOT NULL,
                notability   INTEGER,
                lat          REAL,
                lng          REAL,
                airports     TEXT
            );
            CREATE TABLE IF NOT EXISTS feature_names (
                name_folded TEXT NOT NULL,
                geonameid   INTEGER NOT NULL,
                tier        INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_feature_names_folded
                ON feature_names(name_folded);
            CREATE INDEX IF NOT EXISTS idx_places_country_score
                ON places(country_code, score);
            CREATE INDEX IF NOT EXISTS idx_places_admin1_score
                ON places(country_code, admin1, score);
            CREATE INDEX IF NOT EXISTS idx_admin1_folded ON admin1(folded_name);
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(airports)")}
        for column, decl in _AIRPORT_MIGRATIONS.items():
            if column not in existing:
                _add_column(conn, column, decl)
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(places)")}
        if "satellite" not in existing:  # places tables from before the flag
            _add_column(conn, "satellite", "INTEGER NOT NULL DEFAULT 0", "places")


def _add_column(
    conn: sqlite3.Connection, column: str, decl: str, table: str = "airports"
) -> None:
    """Add a column to ``airports`` (or ``places``); a worker starting at the
    same time may have added it first, which is fine."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc):
            raise


def is_nationalities_seeded() -> bool:
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM nationalities").fetchone()
            return row["n"] > 0
    except Exception:
        return False


def search_nationalities(query: str, limit: int = 10) -> list[dict]:
    """Search nationalities by nationality name or country name."""
    q = query.strip()
    if not q:
        return []

    like = f"%{q}%"
    starts = f"{q}%"

    sql = """
        SELECT nationality, country, country_code
        FROM nationalities
        WHERE
            nationality LIKE :like COLLATE NOCASE
            OR country  LIKE :like COLLATE NOCASE
        ORDER BY
            CASE
                WHEN nationality LIKE :starts COLLATE NOCASE THEN 0
                WHEN country     LIKE :starts COLLATE NOCASE THEN 1
                ELSE 2
            END,
            nationality
        LIMIT :limit
    """
    with get_connection() as conn:
        rows = conn.execute(
            sql,
            {
                "like": like,
                "starts": starts,
                "limit": limit,
            },
        ).fetchall()
    return [dict(r) for r in rows]


def lookup_iata(code: str) -> dict | None:
    """Look up an IATA code and return {iata_code, city, country}, or None.

    Falls back to a DuckDuckGo web search if the code isn't in the DB,
    and persists the result for future lookups.
    """
    code = code.strip().upper()
    if not code:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT iata_code, city, country FROM airports WHERE iata_code = :code",
            {"code": code},
        ).fetchone()
    if row:
        return dict(row)
    replaced = _replaced_code_info(code)
    if replaced:
        return replaced
    return _web_search_iata(code)


def _replaced_code_info(code: str) -> dict | None:
    """A retired code the old curated list used ("PNH", now KTI): the city
    and country of its replacement, so it never needs a web search."""
    from .seed_airports import REPLACED_CODES

    if code not in REPLACED_CODES:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT city, country FROM airports WHERE iata_code = ?",
            (REPLACED_CODES[code],),
        ).fetchone()
    return {"iata_code": code, **dict(row)} if row else None


@functools.cache
def _seed_accented_cities() -> dict[str, str]:
    """Folded name → seeded city name, for seeded names with accents
    ("alesund" → "Ålesund"); NOCASE matching only folds ASCII case."""
    from .seed_airports import AIRPORTS

    return {
        fold_place(city): city
        for _iata, _icao, _name, city, *_ in AIRPORTS
        if fold_place(city) != city.lower()
    }


def _city_spellings(name: str) -> set[str]:
    """The typed city name plus the seed spellings it may stand for:
    accent-folded ("Zürich" → "zurich"), its other St / St. / Saint
    spellings ("St Louis" → "st. louis"), an alias ("Saigon" → "Ho Chi Minh
    City") or an accented seed name ("Alesund" → "Ålesund")."""
    spellings = {name}
    for folded in saint_variants(fold_place(name)):
        spellings.add(folded)
        for table in (CITY_ALIASES, _seed_accented_cities()):
            if folded in table:
                spellings.add(table[folded])
    return spellings


def _stated_countries(stated: str) -> frozenset[str]:
    """ISO codes of the countries a folded last segment names directly
    (country name, ISO code or alias); empty when it names none."""
    from .places_db import stated_countries

    return stated_countries(stated)


def _row_regions(row: sqlite3.Row) -> frozenset[str]:
    return airport_regions(row["iata_code"], row["country_code"], row["region"])


def _in_region(row: sqlite3.Row, region: tuple[str, frozenset[str]]) -> bool:
    """The airport is in the stated region of one of the countries the region
    can be in ("WA" in the US is Washington, in Australia Western Australia)."""
    code, countries = region
    return row["country_code"] in countries and code in _row_regions(row)


@functools.cache
def _curated_city_countries() -> dict[str, frozenset[str]]:
    """Folded curated served-city name → ISO codes of its curated airports
    with scheduled service (Odessa's ODS has none: no Ukraine hint)."""
    from .seed_airports import AIRPORTS, PLACE_DATA_DIR

    with open(PLACE_DATA_DIR / "airports.csv", newline="", encoding="utf-8") as f:
        unscheduled = {r["iata"] for r in csv.DictReader(f) if r["scheduled"] == "0"}
    table: dict[str, set[str]] = {}
    for iata, _icao, _name, city, _country, code, *_ in AIRPORTS:
        if code and iata not in unscheduled:
            table.setdefault(fold_place(city), set()).add(code)
    return {city: frozenset(codes) for city, codes in table.items()}


@functools.cache
def _curated_rank() -> dict[str, int]:
    """Curated code → its position in the curated list, which ranks a city's
    airports (row ids don't: upserts keep old ids on migrated DBs)."""
    from .seed_airports import AIRPORTS

    rank: dict[str, int] = {}
    for a in AIRPORTS:
        rank.setdefault(a[0], len(rank))
    return rank


def _is_country_name(text: str) -> bool:
    from .places_db import country_names

    return fold_place(text) in country_names()


def code_first(text: str) -> bool:
    """An ALL-CAPS three-letter input ("LHR", "NYC") is a code before any
    place; a country name or alias ("USA", "UAE") never is."""
    text = text.strip()
    return bool(re.fullmatch(r"[A-Z]{3}", text)) and not _is_country_name(text)


def three_letter_code(text: str) -> str | None:
    """The airport code a three-letter input stands for: an ALL-CAPS one as
    typed; any other casing only when no place matches ("lhr" → LHR, but
    "Hue" is Huế, "Goa" is Goa). None for anything else."""
    text = text.strip()
    if code_first(text):
        return text
    if not re.fullmatch(r"[A-Za-z]{3}", text) or _is_country_name(text):
        return None
    if _lookup_place(text, 3) or not _is_scheduled_code(text.upper()):
        return None
    return text.upper()


def _single_city_rows(
    rows: list[sqlite3.Row], stated: str | None
) -> list[sqlite3.Row] | None:
    """The matching rows narrowed by the stated segment (country / region),
    or None when they span countries, or regions with none stated."""
    codes = _stated_countries(stated) if stated else frozenset()
    region = stated_region(stated) if stated else None
    if codes or region:
        rows = [
            r
            for r in rows
            if r["country_code"] in codes
            or fold_place(r["country"]) == stated
            or (region and _in_region(r, region))
        ]
    coded = [r for r in rows if r["country_code"]]
    rows = coded or rows
    countries = {r["country_code"] or r["country"].lower() for r in rows}
    if len(countries) != 1:
        return None
    region_sets = [regions for r in rows if (regions := _row_regions(r))]
    if not region and region_sets and not frozenset.intersection(*region_sets):
        return None  # "Portland": Oregon or Maine; Kansas City MCI is both
    return rows


def lookup_city_iata(city: str, max_codes: int = 3) -> str | None:
    """Resolve a typed place ("Berlin", "Berlin, Germany", "BER — Berlin,
    Germany", "Kyoto", "London, Ontario", "Sicily") to up to ``max_codes``
    comma-joined scheduled IATA codes (SerpAPI accepts multiple departure /
    arrival IDs), or None.

    In order:
    1. A bare three-letter code is returned as typed.
    2. A label prefix that is a scheduled code in the airports table is the
       traveller's pick and is returned alone ("LGW — London, …" → "LGW");
       any other prefix stays part of the text.
    3. A curated island / destination ("Sicily", "Kyoto") gives its airports.
    4. The curated tier: curated airports (and web-saved rows) whose served
       city is the typed city — case-insensitive, accent-folded, with its
       St / Saint spellings and ``CITY_ALIASES`` — in curated order. A last
       segment naming a country, ISO code or alias restricts them to that
       country; a region (US state / CA province / AU state / BR state, by
       code or name) to that region. Rows spanning countries, or regions
       with none stated, give no curated answer.
    5. Place resolution (``places_db.resolve``) over every GeoNames place.
       With a curated answer, the place's linked airports follow the
       curated codes when the place is in the same country ("New York" →
       JFK,LGA,EWR); a bigger namesake abroad makes the name ambiguous
       ("Valencia" → None). Without one, the place's airports ("Portland" →
       PDX, "London, Ontario" → YXU, "Zermatt").
    6. Last, the dataset airports whose display city is the typed city.

    Airports without scheduled service are never returned. Local DB only —
    never a web lookup.
    """
    if not city or not city.strip():
        return None
    stripped = city.strip()
    if code_first(stripped):
        return _current_code(stripped)
    from .places_db import names_something_as_typed, no_comma_readings

    readings = no_comma_readings(stripped)
    if readings and not _curated_city_named(stripped):
        if not names_something_as_typed(stripped):
            # "Chicago IL", "Berlin Germany": read as "City, Qualifier" so
            # the curated tier and the qualifier apply
            for reading in readings:
                found = _lookup_place(reading, max_codes)
                if found:
                    return found
    found = _lookup_place(stripped, max_codes)
    if found is None and re.fullmatch(r"[A-Za-z]{3}", stripped):
        if not _is_country_name(stripped) and _is_scheduled_code(stripped.upper()):
            return stripped.upper()  # "lhr", "jfk": no place by that name
    return found


def _is_scheduled_code(code: str) -> bool:
    """The code is a scheduled airport in the DB (no fake codes: "Xqz")."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM airports WHERE iata_code = ? AND scheduled = 1",
                (code,),
            ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _curated_city_named(text: str) -> bool:
    """A curated served city has exactly this (folded) name."""
    return fold_place(text) in _curated_city_countries()


def _current_code(code: str) -> str:
    """A retired code the old curated list used ("PNH") → its replacement
    (KTI); any other code as given."""
    from .seed_airports import REPLACED_CODES

    return REPLACED_CODES.get(code.upper(), code)


def _without_foreign_padding(
    place: "Place", codes: list[str], rows: dict[str, sqlite3.Row]
) -> list[str]:
    """A place's airports in the generator's order, without foreign ones —
    except the place's own (``core.places.is_own_airport``: "Basel" → BSL,
    in France) — unless it has no domestic airport at all ("Lviv" →
    Rzeszów)."""
    from ..core.places import is_own_airport
    from .places_db import airport_distance_km

    folded = fold_place(place.name)
    domestic = [c for c in codes if rows[c]["country_code"] == place.country_code]
    if not domestic:
        return codes
    return [
        c
        for c in codes
        if c in domestic
        or is_own_airport(
            folded,
            fold_place(rows[c]["city"]),
            fold_place(rows[c]["name"]),
            False,
            airport_distance_km(place, c),
        )
    ]


def _lookup_place(stripped: str, max_codes: int) -> str | None:
    """``lookup_city_iata`` steps 2–6 for a non-code text."""
    from .places_db import resolve

    prefix = CODE_PREFIX_RE.match(stripped)
    code = prefix.group(1).upper() if prefix else ""
    after_prefix = stripped[prefix.end() :] if prefix else stripped
    whole_names = _city_spellings(stripped.split(",")[0].strip())
    names = sorted(whole_names | _city_spellings(after_prefix.split(",")[0].strip()))
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT id, iata_code, city, country, country_code, region, type_rank "
                "FROM airports WHERE scheduled = 1 AND ("
                f"city COLLATE NOCASE IN ({','.join('?' * len(names))}) "
                "OR iata_code = ?)",
                [*names, code],
            ).fetchall()
            if code and any(r["iata_code"] == code for r in rows):
                return code
            if code and _current_code(code) != code:
                return _current_code(code)  # "PBI — West Palm Beach" → DJT
            resolution = resolve(stripped, conn)
            linked = [
                c
                for c in (resolution.place.airports if resolution.place else ())
                if c not in NEVER_LINK
            ]
            # the place's airports that are scheduled, with country and city
            linked_rows = {
                r["iata_code"]: r
                for r in conn.execute(
                    "SELECT iata_code, country_code, city, name FROM airports"
                    " WHERE scheduled = 1"
                    f" AND iata_code IN ({','.join('?' * len(linked))})",
                    linked,
                )
            }
            linked_country = {c: r["country_code"] for c, r in linked_rows.items()}
    except sqlite3.Error as exc:  # table missing (unseeded DB) → unresolved
        logger.debug("City airport lookup failed for %r: %s", stripped, exc)
        return None
    place = resolution.place
    place_codes = [c for c in place.airports if c in linked_country] if place else []
    if place and place.geonameid is None:  # curated island / destination
        return ",".join(place_codes[:max_codes]) or None
    parts = [p.strip() for p in stripped.split(",") if p.strip()]
    stated = fold_place(parts[-1]) if len(parts) > 1 else None
    wanted = {fold_place(n) for n in whole_names}
    matching = [r for r in rows if fold_place(r["city"]) in wanted]
    curated_rank = _curated_rank()
    curated = _single_city_rows(
        sorted(
            (
                r
                for r in matching
                if r["type_rank"] is None or r["iata_code"] in curated_rank
            ),
            key=lambda r: (
                curated_rank.get(r["iata_code"], len(curated_rank)),
                r["id"],
            ),
        ),
        stated,
    )
    codes: list[str] = []
    if (
        curated
        and stated
        and place
        and place.country_code != curated[0]["country_code"]
    ):
        # R4: the stated qualifier puts the place in another country than
        # the curated city ("George Town, Penang" is not Grand Cayman's)
        curated = None
    if curated:
        if resolution.contested:
            return None  # "Valencia": Spain's, or Venezuela's bigger one
        codes = [r["iata_code"] for r in curated]
        country = curated[0]["country_code"]
        if place and place.country_code == country:
            # then the place's other airports in that country ("New York" →
            # EWR; not Friedrichshafen for Zürich)
            codes += [
                c
                for c in place_codes
                if c not in codes and linked_country[c] == country
            ]
    elif place:
        codes = _without_foreign_padding(place, place_codes, linked_rows)
    elif not resolution.ambiguous:
        dataset = _single_city_rows(sorted(matching, key=lambda r: r["id"]), stated)
        codes = [r["iata_code"] for r in dataset or ()]
    return ",".join(codes[:max_codes]) or None


def _web_search_iata(code: str) -> dict | None:
    """Search the web for an IATA airport code, use Haiku to extract city/country,
    persist to DB, and return info."""
    try:
        from ddgs import DDGS

        results = list(
            DDGS().text(f"{code} IATA airport code city country", max_results=5)
        )
        if not results:
            return None

        combined = "\n".join(
            f"- {r.get('title', '')}: {r.get('body', '')}" for r in results
        )
        city, country = _llm_extract_city_country(code, combined)
        if not city:
            return None

        info = {"iata_code": code, "city": city, "country": country or "Unknown"}
        try:
            with get_connection() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO airports (iata_code, name, city, country) VALUES (?, ?, ?, ?)",
                    (code, f"{city} Airport", city, info["country"]),
                )
        except Exception:
            pass
        logger.info(f"Web-resolved IATA {code} -> {city}, {info['country']}")
        return info
    except Exception as e:
        logger.warning(f"Web search fallback failed for IATA {code}: {e}")
        return None


def _llm_extract_city_country(
    code: str, search_text: str
) -> tuple[str | None, str | None]:
    """Use Claude Haiku to reliably extract city and country from search results."""
    try:
        import anthropic

        from ..core.config import settings

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"What city and country does the IATA airport code {code} belong to? "
                        f"Here are web search results:\n{search_text}\n\n"
                        f'Reply with ONLY a JSON object: {{"city": "...", "country": "..."}}\n'
                        f"Use the major/nearest city name, not the suburb. No other text."
                    ),
                }
            ],
        )
        text = resp.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text.strip())
        city = data.get("city", "").strip()
        country = data.get("country", "").strip()
        if city and country:
            return city, country
    except Exception as e:
        logger.warning(f"LLM extraction failed for IATA {code}: {e}")
    return None, None


# Autocomplete match classes, best first.
_EXACT_CODE, _CODE_PREFIX, _EXACT_NAME, _NAME_PREFIX, _OTHER = range(5)
# Places considered per autocomplete query (highest score first).
_AUTOCOMPLETE_PLACES = 12
# A curated island / destination ranks like a big city's place.
_HINT_SCORE = 5e9
# A linked airport serving another town ranks at this share of the place's
# score ("san": San Francisco's SFO before San Diego's Tijuana link).
_OTHER_TOWN_SHARE = 0.1
# A place-derived suggestion needs this share of the best match's score.
_AUTOCOMPLETE_MIN_SHARE = 10
# An alternate-name match ranks at this share of its place's score.
_AUTOCOMPLETE_ALT_SHARE = 0.01
# Queries this short suggest places only by exact name or with this many
# people ("sky" is not every Skyline / Skyland).
_SHORT_QUERY = 3
# An airport whose own name starts with the query ranks like a place of
# this score, by size ("kili" → Kilimanjaro International before Kilis).
_AIRPORT_NAME_SCORE = {0: 1e9, 1: 1e8, 2: 1e7}
_SHORT_QUERY_MIN_POPULATION = 100_000


def _autocomplete_places(
    conn: sqlite3.Connection, folded: str
) -> tuple[dict[str, tuple], dict[str, float]]:
    """For the places (and curated islands / destinations) whose name starts
    with the folded query: their linked airports → (match class, place
    score, position in the place's links, place name or None for a curated
    hint, the place's country or None for a hint), and each matched name's
    best score. Own names match by prefix; alternate names of places with
    ≥ 100k people by prefix from four letters ("münch" → München), else
    whole ("milano"). Only places scoring ≥ 1/10 of the best match count
    ("milan": not Milan, Michigan)."""
    from ..core.places import DESTINATION_AIRPORTS, ISLAND_AIRPORTS, REGION_HINTS
    from .places_db import SMALL_PLACE_POPULATION

    linked: dict[str, tuple] = {}
    name_score: dict[str, float] = {}

    def add(name, codes, score, place_cc=None, hint=False, small=False):
        # a village's exact name is only a prefix-class match ("bucu" is
        # Bucharest's București before the hamlet Bucu)
        cls = _EXACT_NAME if name == folded and not small else _NAME_PREFIX
        name_score[name] = max(score, name_score.get(name, 0.0))
        for pos, code in enumerate(codes):
            known = linked.get(code)
            if known is None or (cls, -score, pos) < (known[0], -known[1], known[2]):
                linked[code] = (cls, score, pos, None if hint else name, place_cc)

    hints = {**ISLAND_AIRPORTS, **DESTINATION_AIRPORTS, **REGION_HINTS}
    # an exactly typed hint keeps namesakes abroad out ("yorkshire": no
    # Yorkshire, Virginia; "sylt": no Sylhet)
    hint_country = hints[folded][0] if folded in hints else None
    for name, (_cc, codes) in hints.items():
        # whole names, or prefixes from four letters ("par" is not Park City)
        if name == folded or (len(folded) >= 4 and name.startswith(folded)):
            add(name, codes, _HINT_SCORE, hint=True)
    if len(folded) < 2:
        return linked, name_score
    end = folded + "\uffff"
    rows = conn.execute(
        "SELECT n.name_folded, n.tier, p.score, p.airports, p.country_code,"
        " p.population "
        "FROM place_names n JOIN places p ON p.geonameid = n.geonameid "
        "WHERE p.population > 0 AND p.airports != '' "
        "AND (length(:q) > :short OR n.name_folded = :q OR p.population >= :big) "
        "AND ("
        "(n.tier = 0 AND n.name_folded >= :q AND n.name_folded < :end) "
        "OR (n.tier = 1 AND n.name_folded = :q AND length(:q) >= 4) "
        "OR (n.tier = 1 AND length(:q) >= 4 AND p.population >= 100000"
        " AND n.name_folded >= :q AND n.name_folded < :end)) "
        # own names of real towns first, then by score (alternates of big
        # places before villages: "münch" reaches München)
        "ORDER BY (n.tier = 0 AND p.population >= :small) DESC, p.score DESC "
        "LIMIT :n",
        {
            "q": folded,
            "end": end,
            "n": _AUTOCOMPLETE_PLACES,
            "short": _SHORT_QUERY,
            "big": _SHORT_QUERY_MIN_POPULATION,
            "small": SMALL_PLACE_POPULATION,
        },
    ).fetchall()
    scored = [
        (r["score"] * (_AUTOCOMPLETE_ALT_SHARE if r["tier"] else 1.0), r) for r in rows
    ]  # alternates rank far below own names (Syracuse's stray "milan")
    # the share threshold counts own names of real towns when there are any
    # ("kota": Kota, Rajasthan, not Malay "Kota …" alternates of megacities);
    # villages alone don't set it ("cologne": Köln, not Cologne, Minnesota)
    own = [
        sc
        for sc, r in scored
        if not r["tier"] and r["population"] >= SMALL_PLACE_POPULATION
    ]
    best = max(own or [sc for sc, _ in scored], default=0)
    best_own = max(own, default=0)
    for sc, r in scored:
        if r["tier"] and r["name_folded"] != folded and sc < best_own:
            continue  # an alternate prefix must beat every own-name match
        if hint_country and r["country_code"] != hint_country:
            continue
        if sc * _AUTOCOMPLETE_MIN_SHARE >= best:
            add(
                r["name_folded"],
                r["airports"].split(),
                sc,
                r["country_code"],
                small=r["population"] < SMALL_PLACE_POPULATION,
            )
    return linked, name_score


def search_airports(query: str, limit: int = 10) -> list[dict]:
    """Autocomplete: airports by IATA code, city, airport name or country,
    plus the airports linked to GeoNames places (and curated islands /
    destinations) whose folded name starts with the query ("kyoto" → KIX,
    ITM; "zurich" → ZRH). A place adds only its own-country airports, and
    only places scoring ≥ 1/10 of the best match count. Order: exact code,
    code prefix, exact city / place name, name prefix, anything else (a
    lower-case three-letter text that names a place lists the place before
    the code: "hue" → HUI, "HUE" → HUE); within a class the more notable
    place first ("lon": London before Long Beach), its curated airports in
    curated order, then its other links, then bigger airports (type_rank)
    and the name. Airports without scheduled service only for their exact
    code. Response rows: iata_code, name, city, country, country_code."""
    q = query.strip()
    if not q:
        return []
    upper = q.upper()
    folded = fold_place(q)
    with get_connection() as conn:
        linked, name_score = _autocomplete_places(conn, folded)
        codes = ",".join(f":p{i}" for i in range(len(linked))) or "''"
        rows = conn.execute(
            "SELECT iata_code, name, city, country, country_code, type_rank,"
            " scheduled FROM airports"
            " WHERE iata_code = :upper OR iata_code LIKE :code_prefix"
            " OR city LIKE :like COLLATE NOCASE OR name LIKE :like COLLATE NOCASE"
            f" OR country LIKE :like COLLATE NOCASE OR iata_code IN ({codes})",
            {
                "upper": upper,
                "code_prefix": f"{upper}%",
                # up to three letters: prefixes only (a contains-match on
                # "a" is most of the table; "sky" is in many airport names)
                "like": f"{q}%" if len(q) < 4 else f"%{q}%",
                **{f"p{i}": code for i, code in enumerate(linked)},
            },
        ).fetchall()
    curated = _curated_rank()
    place_first = (
        len(q) == 3
        and not q.isupper()
        and any(v[0] == _EXACT_NAME for v in linked.values())
    )
    needle = folded if len(q) >= 4 else None

    def rank(r: sqlite3.Row) -> tuple | None:
        code, city = r["iata_code"], fold_place(r["city"])
        score, pos = name_score.get(city, 0.0), 99
        if code == upper:
            cls = _NAME_PREFIX if place_first else _EXACT_CODE
        elif code.startswith(upper):
            cls = _CODE_PREFIX
        elif city == folded:
            cls = _EXACT_NAME
        elif city.startswith(folded):
            cls = _NAME_PREFIX
        elif needle and fold_place(r["name"] or "").startswith(needle):
            # the airport's own name ("kili" → Kilimanjaro International),
            # ranked like a place of its size
            cls = _NAME_PREFIX
            score = _AIRPORT_NAME_SCORE.get(r["type_rank"], 0.0)
        else:
            cls, score = _OTHER, 0.0
        link = linked.get(code)
        if link and link[4] is not None and link[4] != r["country_code"]:
            link = None  # a place suggests only airports in its own country
        if link:
            place_cls, place_score, place_pos, place_name, _cc = link
            if place_name is not None and place_name != city and place_pos > 0:
                place_score *= _OTHER_TOWN_SHARE  # its first link is its own
            if (place_cls, -place_score) < (cls, -score):
                cls, score, pos = place_cls, place_score, place_pos
        elif cls == _OTHER and not (
            needle
            and needle in " ".join(fold_place(r[k] or "") for k in ("name", "country"))
        ):
            return None  # matched only through a dropped place link
        type_rank = r["type_rank"] if r["type_rank"] is not None else 9
        # R7: a place's bigger airport before its smaller ones ("bucu" → OTP)
        return (cls, -score, type_rank, curated.get(code, len(curated)), pos, r["name"])

    ranked = []
    for r in rows:
        if r["iata_code"] != upper and r["scheduled"] not in (None, 1):
            continue
        key = rank(r)
        if key is not None:
            ranked.append((key, r))
    ranked.sort(key=lambda kr: kr[0])
    if ranked and ranked[0][0][0] < _OTHER:
        # R7: no padding with mere "contains" matches below real ones
        ranked = [kr for kr in ranked if kr[0][0] < _OTHER]
    keys = ("iata_code", "name", "city", "country", "country_code")
    return [{k: r[k] for k in keys} for _, r in ranked[:limit]]
