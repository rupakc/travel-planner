import json
import logging
import re
import sqlite3
from pathlib import Path

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


def lookup_city_iata(city: str, max_codes: int = 2) -> str | None:
    """Resolve a city name (optionally 'City, Country') to IATA airport codes.

    Returns up to max_codes codes comma-joined (SerpAPI accepts multiple
    departure/arrival IDs), or None if the city isn't in the airports table.
    Seed data lists major airports first, so row order is the tiebreaker.
    """
    if not city or not city.strip():
        return None
    stripped = city.strip()
    if re.match(r"^[A-Za-z]{3}$", stripped):
        return stripped.upper()
    parts = [p.strip() for p in stripped.split(",")]
    city_name, country = parts[0], (parts[1] if len(parts) > 1 else None)
    with get_connection() as conn:
        if country:
            rows = conn.execute(
                "SELECT iata_code FROM airports WHERE lower(city) = :city "
                "AND lower(country) = :country LIMIT :n",
                {"city": city_name.lower(), "country": country.lower(), "n": max_codes},
            ).fetchall()
            if rows:
                return ",".join(r["iata_code"] for r in rows)
        rows = conn.execute(
            "SELECT iata_code FROM airports WHERE lower(city) = :city LIMIT :n",
            {"city": city_name.lower(), "n": max_codes},
        ).fetchall()
    if not rows:
        return None
    return ",".join(r["iata_code"] for r in rows)


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
