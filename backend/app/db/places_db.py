"""Resolve a typed place ("Kyoto", "London, Ontario", "Munich, Bavaria",
"Sicily", "Japan") to one ranked place and its scheduled airports, from the
GeoNames places / place_names / admin1 tables (see ``data/README.md``).

Local DB only: one indexed query for the names plus one for first-level
divisions when a region or country is stated. Never a web lookup.
"""

import csv
import functools
import logging
import math
import re
import sqlite3
from dataclasses import dataclass

from ..core.places import (
    _REGION_NAMES,
    CITY_ALIASES,
    COUNTRY_ALIASES,
    DESTINATION_AIRPORTS,
    ISLAND_AIRPORTS,
    fold_place,
    saint_variants,
    stated_region,
)
from .database import get_connection

logger = logging.getLogger(__name__)

# A place matched only by an alternate name ("Cologne" for Köln, "Venice" for
# Venezia) competes with this fraction of its score: alternates are noisier
# than own names ("Cancun" is also an alternate of Changchun), but a famous
# place's alternate must still beat small namesakes ("Venice", Florida).
# Calibrated on tests/data/golden_places.csv (see task-3 report).
ALT_NAME_PENALTY = 0.0135
# Shorter alternate names are mostly abbreviations and never match.
MIN_ALT_NAME_LENGTH = 4
# The winner needs this many times the score of the next candidate.
DOMINANCE = 3.0

# "BER — Berlin, Germany" (the UI's airport label) → "Berlin, Germany"
_CODE_PREFIX_RE = re.compile(r"^\s*([A-Za-z]{3})\s*(?:[—–]|\s-)\s*")

_PLACE_COLUMNS = (
    "p.geonameid, p.name, p.country_code, p.admin1, p.population, p.score, "
    "p.airports, p.lat, p.lng"
)


@dataclass(frozen=True)
class Place:
    """A resolved place. ``airports`` are its linked scheduled airports, best
    first; ``geonameid`` is None for a curated island / destination hint."""

    name: str
    country_code: str
    airports: tuple[str, ...]
    geonameid: int | None = None
    admin1: str | None = None
    population: int = 0
    score: float = 0.0
    alternate: bool = False  # matched by an alternate name only
    lat: float | None = None
    lng: float | None = None


@functools.cache
def country_names() -> dict[str, str]:
    """Folded country name (dataset spelling) or alias → ISO code."""
    from .seed_airports import PLACE_DATA_DIR

    table: dict[str, str] = {}
    with open(PLACE_DATA_DIR / "airports.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["country_code"]:
                table[fold_place(row["country"])] = row["country_code"]
    table.update(COUNTRY_ALIASES)
    return table


@functools.cache
def _iso_codes() -> frozenset[str]:
    return frozenset(country_names().values())


def stated_countries(stated: str) -> frozenset[str]:
    """ISO codes of the countries a folded segment names: a country name,
    alias or ISO code ("de" → {DE}); empty when it names none."""
    codes = set()
    if stated in country_names():
        codes.add(country_names()[stated])
    if len(stated) == 2 and stated.upper() in _iso_codes():
        codes.add(stated.upper())
    return frozenset(codes)


# Full names of the CA / AU / BR region codes, to find their GeoNames admin1
# rows (US admin1 codes are the state codes themselves).
_REGION_FULL_NAMES: dict[tuple[str, str], tuple[str, ...]] = {}
for _name, (_code, _cc) in _REGION_NAMES.items():
    if _cc != "US":
        _REGION_FULL_NAMES[(_code, _cc)] = (_name,)
_REGION_FULL_NAMES[("df", "BR")] = ("distrito federal", "federal district")


@dataclass(frozen=True)
class _Stated:
    """What a stated segment can mean: countries and/or admin1 regions."""

    countries: frozenset[str]
    admin1: frozenset[tuple[str, str]]

    def admits(self, country_code: str, admin1: str | None) -> bool:
        return country_code in self.countries or (country_code, admin1) in self.admin1


def _hint(name: str, stated: list[str], display: str) -> Place | None:
    """A curated island / destination for the folded name, unless a stated
    country names another country."""
    hint = ISLAND_AIRPORTS.get(name) or DESTINATION_AIRPORTS.get(name)
    if not hint:
        return None
    country, airports = hint
    for segment in stated:
        countries = stated_countries(segment)
        if countries and country not in countries:
            return None
    return Place(name=display, country_code=country, airports=airports)


def _strip_known_prefix(conn: sqlite3.Connection, text: str) -> str:
    """Drop a label prefix that is a scheduled airport code ("BER — Berlin,
    Germany"); any other prefix stays part of the text."""
    prefix = _CODE_PREFIX_RE.match(text)
    if (
        prefix
        and conn.execute(
            "SELECT 1 FROM airports WHERE iata_code = ? AND scheduled = 1",
            (prefix.group(1).upper(),),
        ).fetchone()
    ):
        return text[prefix.end() :]
    return text


def _parse(text: str) -> tuple[str, list[str], str]:
    """(folded city, folded stated segments after it, city as typed)."""
    raw = [s.strip() for s in text.split(",") if fold_place(s)]
    if not raw:
        return "", [], ""
    return fold_place(raw[0]), [fold_place(s) for s in raw[1:]], raw[0]


def _name_variants(city: str) -> list[str]:
    """The folded city plus its St / Saint spellings and alias target."""
    names = set()
    for name in saint_variants(city):
        names.add(name)
        if name in CITY_ALIASES:
            names.add(fold_place(CITY_ALIASES[name]))
    return sorted(names)


def _stated_meanings(conn: sqlite3.Connection, stated: list[str]) -> list[_Stated]:
    """Each recognised stated segment's readings (one admin1 query for all);
    unrecognised segments ("Narnia") are dropped."""
    lookups: dict[str, tuple[str, str | None]] = {}  # admin1 name → (segment, cc)
    for segment in stated:
        lookups.setdefault(segment, (segment, None))
        region = stated_region(segment)
        if region:
            code, countries = region
            for cc in countries:
                for full in _REGION_FULL_NAMES.get((code, cc), ()):
                    lookups.setdefault(full, (segment, cc))
    rows = conn.execute(
        "SELECT code, folded_name FROM admin1 WHERE folded_name IN "
        f"({','.join('?' * len(lookups))})",
        list(lookups),
    ).fetchall()
    found: dict[str, set[tuple[str, str]]] = {s: set() for s in stated}
    for row in rows:
        segment, only_cc = lookups[row["folded_name"]]
        cc, _, admin = row["code"].partition(".")
        if only_cc is None or cc == only_cc:
            found[segment].add((cc, admin))
    meanings = []
    for segment in stated:
        admin1 = set(found[segment])
        region = stated_region(segment)
        if region and "US" in region[1]:
            admin1.add(("US", region[0].upper()))
        countries = stated_countries(segment)
        if countries or admin1:
            meanings.append(_Stated(countries, frozenset(admin1)))
    return meanings


def _row_place(row: sqlite3.Row, score: float, alternate: bool = False) -> Place:
    return Place(
        name=row["name"],
        country_code=row["country_code"],
        airports=tuple(row["airports"].split()),
        geonameid=row["geonameid"],
        admin1=row["admin1"],
        population=row["population"],
        score=score,
        alternate=alternate,
        lat=row["lat"],
        lng=row["lng"],
    )


def _dominant(candidates: list[Place]) -> Place | None:
    """The highest-scoring candidate when it has ``DOMINANCE`` times the
    score of every rival, or when every close rival is in the same country
    and flies from the same airport ("Kansas City", Missouri / Kansas)."""
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda p: -p.score)
    top = ranked[0]
    for rival in ranked[1:]:
        if top.score >= DOMINANCE * rival.score:
            break
        if (
            rival.country_code != top.country_code
            or rival.airports[:1] != top.airports[:1]
        ):
            return None
    return top


def _curated_countries(names: list[str]) -> frozenset[str]:
    """Countries of curated airports serving a city by one of these names."""
    from .database import _curated_city_countries

    table = _curated_city_countries()
    return frozenset(cc for n in names for cc in table.get(n, ()))


def _name_candidates(conn: sqlite3.Connection, names: list[str]) -> list[Place]:
    """Places named so (own name, or alternate at a penalty); population-0
    places never count."""
    rows = conn.execute(
        f"SELECT n.tier, n.name_folded, {_PLACE_COLUMNS} FROM place_names n "
        "JOIN places p ON p.geonameid = n.geonameid "
        f"WHERE n.name_folded IN ({','.join('?' * len(names))}) "
        "AND p.population > 0",
        names,
    ).fetchall()
    best: dict[int, Place] = {}
    for row in rows:
        if row["tier"] != 0 and len(row["name_folded"]) < MIN_ALT_NAME_LENGTH:
            continue  # "can" (Caen), "bol": abbreviations, not names
        score = row["score"] * (1.0 if row["tier"] == 0 else ALT_NAME_PENALTY)
        known = best.get(row["geonameid"])
        if known is None or score > known.score:
            best[row["geonameid"]] = _row_place(row, score, row["tier"] != 0)
    return list(best.values())


def _top_place(conn: sqlite3.Connection, where: str, params: list) -> list[Place]:
    rows = conn.execute(
        f"SELECT {_PLACE_COLUMNS} FROM places p WHERE {where} "
        "AND p.population > 0 ORDER BY p.score DESC LIMIT 2",
        params,
    ).fetchall()
    return [_row_place(r, r["score"]) for r in rows]


def _region_candidates(conn: sqlite3.Connection, name: str) -> list[Place]:
    """An admin1 name typed alone ("Bavaria") → its two top places; a name
    several countries use for a division counts as no region."""
    rows = conn.execute(
        "SELECT code FROM admin1 WHERE folded_name = ?", (name,)
    ).fetchall()
    if len(rows) != 1:
        return []
    cc, _, admin = rows[0]["code"].partition(".")
    return _top_place(conn, "p.country_code = ? AND p.admin1 = ?", [cc, admin])


@dataclass(frozen=True)
class Resolution:
    """A resolved place, or why there is none: ``ambiguous`` when several
    candidates tie (as opposed to no candidate at all)."""

    place: Place | None
    ambiguous: bool = False
    # A bigger own-name namesake abroad rivals the curated city ("Valencia")
    contested: bool = False


def _pick(candidates: list[Place]) -> Resolution:
    place = _dominant(candidates)
    return Resolution(place, ambiguous=place is None and bool(candidates))


def _bigger_namesake(curated: Place, candidates: list[Place]) -> bool:
    """A place in another country, named so in its own right, as populous as
    the curated city's place and within the dominance window ("Valencia":
    Venezuela's is bigger than Spain's) makes the name ambiguous."""
    return any(
        p.country_code != curated.country_code
        and not p.alternate
        and p.population >= curated.population
        and DOMINANCE * p.score > curated.score
        for p in candidates
    )


# Nearest linked airport farther than this: the place only has the
# generator's distant fallback links (Bol, Chad → N'Djamena).
REACH_KM = 100.0


@functools.cache
def _dataset_airports() -> tuple[dict[str, tuple[float, float]], tuple[str, ...]]:
    """Every dataset airport → (lat, lng), and the unscheduled ones."""
    from .seed_airports import PLACE_DATA_DIR

    with open(PLACE_DATA_DIR / "airports.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    points = {r["iata"]: (float(r["lat"]), float(r["lng"])) for r in rows}
    return points, tuple(r["iata"] for r in rows if r["scheduled"] == "0")


def airport_distance_km(place: Place, code: str) -> float:
    """Great-circle distance from the place to an airport (inf if unknown)."""
    point = _dataset_airports()[0].get(code)
    if point is None or place.lat is None or place.lng is None:
        return math.inf
    lat1, lng1, lat2, lng2 = map(math.radians, (place.lat, place.lng, *point))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _reachable(candidates: list[Place]) -> list[Place]:
    """Candidates with an airport within ``REACH_KM`` — linked, or one
    without scheduled service (Odesa's ODS) — when any has one: a town with
    an airport beats a namesake that only has a distant fallback ("Bol":
    Croatia's island town, not Bol, Chad)."""
    unscheduled = _dataset_airports()[1]
    near = [
        p
        for p in candidates
        if any(
            airport_distance_km(p, c) <= REACH_KM for c in (*p.airports, *unscheduled)
        )
    ]
    return near or candidates


def _resolve(conn: sqlite3.Connection, text: str) -> Resolution:
    city, stated, typed = _parse(_strip_known_prefix(conn, text))
    if not city:
        return Resolution(None)
    hint = _hint(city, stated, typed)
    if hint:
        return Resolution(hint)
    if not stated and city in country_names():
        # A country typed alone → its highest-scoring place (the capital, or
        # the main gateway city: Istanbul, Zürich, Sydney, New York City).
        top = _top_place(conn, "p.country_code = ?", [country_names()[city]])
        return Resolution(top[0] if top else None)
    names = _name_variants(city)
    candidates = _name_candidates(conn, names)
    if stated:
        meanings = _stated_meanings(conn, stated)
        candidates = [
            p
            for p in candidates
            if all(m.admits(p.country_code, p.admin1) for m in meanings)
        ]
        if meanings and not candidates:
            return Resolution(None)  # "Berlin, Japan"
    elif not candidates:
        return _pick(_region_candidates(conn, city))
    curated = _curated_countries(names)
    preferred = [p for p in candidates if p.country_code in curated]
    if not preferred:
        return _pick(_reachable(candidates))
    result = _pick(_reachable(preferred))
    if result.place and _bigger_namesake(result.place, candidates):
        return Resolution(None, ambiguous=True, contested=True)
    return result


def resolve_place(text: str, conn: sqlite3.Connection | None = None) -> Place | None:
    """The place a typed text names, or None when unknown or ambiguous.

    1. A curated island / destination ("Sicily", "Machu Picchu") wins.
    2. A country typed alone ("Japan") → its highest-scoring place.
    3. Candidates: places whose own or alternate name (folded, with its
       St / Saint spellings) is the city; alternates compete at
       ``ALT_NAME_PENALTY`` of their score; population-0 places never count.
    4. Stated segments filter them: a country (name, alias, ISO code), a
       region code (US / CA / AU / BR) or any first-level division name
       ("Bavaria", "Ontario", "England"); every reading counts ("CA":
       Canada or California). A stated country with no candidate → None.
    5. Curated airports' cities pick the country when candidates exist
       there, unless a bigger own-name namesake elsewhere is within the
       dominance window ("Valencia": Spain or Venezuela → None).
    6. Winner: ``DOMINANCE`` × the next candidate's score, else None
       ("Springfield", "San Jose"). A division name typed alone resolves to
       its dominant place.
    """
    return resolve(text, conn).place


def resolve(text: str, conn: sqlite3.Connection | None = None) -> Resolution:
    """``resolve_place`` with the reason when there is no place."""
    if not text or not text.strip():
        return Resolution(None)
    try:
        if conn is not None:
            return _resolve(conn, text)
        with get_connection() as own:
            return _resolve(own, text)
    except sqlite3.Error as exc:  # tables missing (unseeded DB) → unresolved
        logger.debug("Place resolution failed for %r: %s", text, exc)
        return Resolution(None)
