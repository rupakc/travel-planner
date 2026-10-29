import functools
import json
import logging
import re
import sqlite3
from pathlib import Path

from ..core.places import _REGION_CODES, _US_STATES

logger = logging.getLogger(__name__)


def _db_path() -> Path:
    from ..core.config import settings

    p = Path(settings.data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / "airports.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


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
        """)


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


def is_seeded() -> bool:
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM airports").fetchone()
            return row["n"] > 0
    except Exception:
        return False


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
    return _web_search_iata(code)


# "BER — Berlin, Germany" (the UI's airport label) → "Berlin, Germany"
_IATA_PREFIX_RE = re.compile(r"^\s*([A-Za-z]{3})\s*(?:[—–]|\s-)\s*")

# Other names people type for a country → its ISO code in the airports table.
_COUNTRY_CODE_ALIASES: dict[str, str] = {
    "uk": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "britain": "GB",
    "great britain": "GB",
    "usa": "US",
    "america": "US",
    "united states of america": "US",
    "uae": "AE",
    "holland": "NL",
    "the netherlands": "NL",
    "korea": "KR",
    "republic of korea": "KR",
    "czechia": "CZ",
    "turkiye": "TR",
    "türkiye": "TR",
}


@functools.cache
def _seed_country_codes() -> dict[str, str]:
    """Seeded country name / ISO code (lowercase) → ISO code."""
    from .seed_airports import AIRPORTS

    table: dict[str, str] = {}
    for _iata, _icao, _name, _city, country, code, *_ in AIRPORTS:
        if code:
            table[country.lower()] = code
            table[code.lower()] = code
    return table


def _stated_country_codes(stated: str) -> frozenset[str] | None:
    """ISO codes a typed last segment can name, or None when it isn't a
    recognised country name, ISO code, alias or region code ("Bavaria")."""
    codes = set(_REGION_CODES.get(stated, ()))  # "wa": Washington / W. Australia
    if stated in _seed_country_codes():
        codes.add(_seed_country_codes()[stated])
    if stated in _COUNTRY_CODE_ALIASES:
        codes.add(_COUNTRY_CODE_ALIASES[stated])
    if stated in _US_STATES.values():  # "Paris, Texas"
        codes.add("US")
    return frozenset(codes) or None


def lookup_city_iata(city: str, max_codes: int = 3) -> str | None:
    """Resolve a typed place ("Berlin", "Berlin, Germany", "BER — Berlin,
    Germany") to up to ``max_codes`` comma-joined IATA codes (SerpAPI accepts
    multiple departure/arrival IDs), or None.

    A label prefix that is a code in the airports table is the traveller's
    pick and is returned alone ("LGW — London, …" → "LGW"); any other prefix
    stays part of the text. Otherwise an exact, case-insensitive match on the
    city (first comma segment). A last segment that names a country, ISO
    code, alias or region code restricts the match; an unrecognised one
    ("Bavaria") is ignored. Web-saved rows (no country_code) count only when
    no coded row matches. Matches spanning more than one country are
    ambiguous and resolve to None. Seed data lists each city's primary
    airport first, so insertion order ranks the codes. Local DB only — one
    indexed query, never a web lookup.
    """
    if not city or not city.strip():
        return None
    stripped = city.strip()
    if re.match(r"^[A-Za-z]{3}$", stripped):
        return stripped.upper()
    prefix = _IATA_PREFIX_RE.match(stripped)
    code = prefix.group(1).upper() if prefix else ""
    after_prefix = stripped[prefix.end() :] if prefix else stripped
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT iata_code, city, country, country_code FROM airports "
                "WHERE city = :whole COLLATE NOCASE OR city = :after COLLATE NOCASE "
                "OR iata_code = :code ORDER BY id",
                {
                    "whole": stripped.split(",")[0].strip(),
                    "after": after_prefix.split(",")[0].strip(),
                    "code": code,
                },
            ).fetchall()
    except sqlite3.Error as exc:  # table missing (unseeded DB) → unresolved
        logger.debug("City airport lookup failed for %r: %s", city, exc)
        return None
    if code and any(r["iata_code"] == code for r in rows):
        return code
    parts = [p.strip() for p in stripped.split(",") if p.strip()]
    city_name = parts[0].lower()
    rows = [r for r in rows if r["city"].lower() == city_name]
    stated = " ".join(parts[-1].lower().split()) if len(parts) > 1 else None
    codes = _stated_country_codes(stated) if stated else None
    if codes:
        rows = [
            r
            for r in rows
            if r["country_code"] in codes or r["country"].lower() == stated
        ]
    coded = [r for r in rows if r["country_code"]]
    rows = coded or rows
    countries = {r["country_code"] or r["country"].lower() for r in rows}
    if len(countries) != 1:
        return None
    return ",".join(r["iata_code"] for r in rows[:max_codes])


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


def search_airports(query: str, limit: int = 10) -> list[dict]:
    """Search airports by IATA code, city, airport name, or country."""
    q = query.strip()
    if not q:
        return []

    upper = q.upper()
    like = f"%{q}%"

    sql = """
        SELECT iata_code, name, city, country, country_code
        FROM airports
        WHERE
            iata_code = :upper
            OR iata_code LIKE :like_upper
            OR city     LIKE :like COLLATE NOCASE
            OR name     LIKE :like COLLATE NOCASE
            OR country  LIKE :like COLLATE NOCASE
        ORDER BY
            CASE
                WHEN iata_code = :upper              THEN 0
                WHEN iata_code LIKE :like_upper      THEN 1
                WHEN city LIKE :like COLLATE NOCASE  THEN 2
                ELSE 3
            END,
            city
        LIMIT :limit
    """
    with get_connection() as conn:
        rows = conn.execute(
            sql,
            {
                "upper": upper,
                "like_upper": f"{upper}%",
                "like": like,
                "limit": limit,
            },
        ).fetchall()
    return [dict(r) for r in rows]
