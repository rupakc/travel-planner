import csv
import functools
import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..core.places import CITY_ALIASES, fold_place, saint_variants, stated_region
from .airport_regions import airport_regions

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
                airports     TEXT
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


def _add_column(conn: sqlite3.Connection, column: str, decl: str) -> None:
    """Add a column to ``airports``; a worker starting at the same time may
    have added it first, which is fine."""
    try:
        conn.execute(f"ALTER TABLE airports ADD COLUMN {column} {decl}")
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
            OR country  LIKE :like COLLATE NOCASE)
          AND (COALESCE(scheduled, 1) = 1 OR iata_code = :upper)
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


# "BER — Berlin, Germany" (the UI's airport label) → "Berlin, Germany"
_IATA_PREFIX_RE = re.compile(r"^\s*([A-Za-z]{3})\s*(?:[—–]|\s-)\s*")


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


@functools.cache
def _three_letter_places() -> frozenset[str]:
    """Curated cities and islands / destinations whose name is three letters
    ("Goa", "Kos", "Fes"): typed so, they are places, not codes."""
    from ..core.places import DESTINATION_AIRPORTS, ISLAND_AIRPORTS
    from .seed_airports import AIRPORTS

    names = {fold_place(a[3]) for a in AIRPORTS}
    names |= ISLAND_AIRPORTS.keys() | DESTINATION_AIRPORTS.keys()
    return frozenset(n for n in names if len(n) == 3)


def looks_like_code(text: str) -> bool:
    """A bare three-letter airport / metro code ("LHR", "lhr", "NYC"), not a
    three-letter place name typed as a word ("Goa", "Kos"; "GOA" stays the
    Genoa code)."""
    text = text.strip()
    if not re.fullmatch(r"[A-Za-z]{3}", text):
        return False
    return text.isupper() or fold_place(text) not in _three_letter_places()


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
    if looks_like_code(stripped):
        return stripped.upper()
    from .places_db import resolve

    prefix = _IATA_PREFIX_RE.match(stripped)
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
            resolution = resolve(stripped, conn)
            linked = resolution.place.airports if resolution.place else ()
            # the place's airports that are scheduled, with their countries
            linked_country = dict(
                conn.execute(
                    "SELECT iata_code, country_code FROM airports WHERE scheduled = 1"
                    f" AND iata_code IN ({','.join('?' * len(linked))})",
                    linked,
                ).fetchall()
            )
    except sqlite3.Error as exc:  # table missing (unseeded DB) → unresolved
        logger.debug("City airport lookup failed for %r: %s", city, exc)
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
        codes = place_codes
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


def _autocomplete_places(
    conn: sqlite3.Connection, folded: str
) -> tuple[dict[str, tuple[int, float, int, str | None]], dict[str, float]]:
    """For the places (and curated islands / destinations) whose name starts
    with the folded query: their linked airports → (match class, place
    score, position in the place's links, place name or None for a curated
    hint), and each matched name's best
    score. Own names match by prefix; alternate names ("milano") whole."""
    from ..core.places import DESTINATION_AIRPORTS, ISLAND_AIRPORTS

    linked: dict[str, tuple[int, float, int, str | None]] = {}
    name_score: dict[str, float] = {}

    def add(name, codes, score, hint=False):
        cls = _EXACT_NAME if name == folded else _NAME_PREFIX
        name_score[name] = max(score, name_score.get(name, 0.0))
        for pos, code in enumerate(codes):
            known = linked.get(code)
            if known is None or (cls, -score, pos) < (known[0], -known[1], known[2]):
                linked[code] = (cls, score, pos, None if hint else name)

    for name, (_cc, codes) in {**ISLAND_AIRPORTS, **DESTINATION_AIRPORTS}.items():
        if name.startswith(folded):
            add(name, codes, _HINT_SCORE, hint=True)
    if len(folded) < 2:
        return linked, name_score
    rows = conn.execute(
        "SELECT n.name_folded, p.score, p.airports "
        "FROM place_names n JOIN places p ON p.geonameid = n.geonameid "
        "WHERE p.population > 0 AND p.airports != '' AND ("
        "(n.tier = 0 AND n.name_folded >= ? AND n.name_folded < ?) "
        "OR (n.name_folded = ? AND length(?) >= 4)) "
        "ORDER BY p.score DESC LIMIT ?",
        (folded, folded + "\uffff", folded, folded, _AUTOCOMPLETE_PLACES),
    ).fetchall()
    for r in rows:
        add(r["name_folded"], r["airports"].split(), r["score"])
    return linked, name_score


def search_airports(query: str, limit: int = 10) -> list[dict]:
    """Autocomplete: airports by IATA code, city, airport name or country,
    plus the airports linked to GeoNames places (and curated islands /
    destinations) whose folded name starts with the query ("kyoto" → KIX,
    ITM; "zurich" → ZRH). Order: exact code, code prefix, exact city / place
    name, name prefix, anything else; within a class the more notable place
    first ("lon": London before Long Beach), its curated airports in curated
    order, then its other links, then bigger airports (type_rank) and the
    name. Airports without scheduled service only for their exact code.
    Response rows: iata_code, name, city, country, country_code."""
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
                # one or two letters: prefixes only (a contains-match on
                # "a" is most of the table)
                "like": f"{q}%" if len(q) < 3 else f"%{q}%",
                **{f"p{i}": code for i, code in enumerate(linked)},
            },
        ).fetchall()
    curated = _curated_rank()

    def rank(r: sqlite3.Row) -> tuple:
        code, city = r["iata_code"], fold_place(r["city"])
        score, pos = name_score.get(city, 0.0), 99
        if code == upper:
            cls = _EXACT_CODE
        elif code.startswith(upper):
            cls = _CODE_PREFIX
        elif city == folded:
            cls = _EXACT_NAME
        elif city.startswith(folded):
            cls = _NAME_PREFIX
        else:
            cls, score = _OTHER, 0.0
        if code in linked:
            place_cls, place_score, place_pos, place_name = linked[code]
            if place_name is not None and place_name != city:
                place_score *= _OTHER_TOWN_SHARE
            if (place_cls, -place_score) < (cls, -score):
                cls, score, pos = place_cls, place_score, place_pos
        type_rank = r["type_rank"] if r["type_rank"] is not None else 9
        return (cls, -score, curated.get(code, len(curated)), pos, type_rank, r["name"])

    visible = [
        r for r in rows if r["iata_code"] == upper or r["scheduled"] in (None, 1)
    ]
    visible.sort(key=rank)
    keys = ("iata_code", "name", "city", "country", "country_code")
    return [{k: r[k] for k in keys} for r in visible[:limit]]
