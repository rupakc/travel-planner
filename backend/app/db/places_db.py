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
from dataclasses import dataclass, replace

from ..core.places import (
    _REGION_NAMES,
    AIRPORT_NAME_WORDS,
    CITY_ALIASES,
    CODE_PREFIX_RE,
    COUNTRY_ALIASES,
    DESTINATION_AIRPORTS,
    EXONYMS,
    GENERIC_PLACE_WORDS,
    ISLAND_AIRPORTS,
    REGION_HINTS,
    SAINT_EXCEPTIONS,
    fold_place,
    saint_variants,
    stated_region,
)
from .database import get_connection

logger = logging.getLogger(__name__)

# Alternate names count only when no place has the typed name as its own
# ("Olbia" is Olbia, not Antalya's alternate); exonyms whose own-name
# namesakes would win ("Cologne", "Mecca") are in core.places.EXONYMS.
# Shorter alternate names are mostly abbreviations and never match.
MIN_ALT_NAME_LENGTH = 4
# A place this small wins only alone, curated or hinted ("Praslin", Saint
# Lucia; "Gap", Pennsylvania).
SMALL_PLACE_POPULATION = 15_000
# R2: a winner this small whose nearest airport is over CONFIDENCE_KM away is
# a guess (Monteverde, Italy for the Costa Rican cloud forest) → None.
CONFIDENCE_POPULATION = 5_000
CONFIDENCE_KM = 100.0
# R3: an alternate-name place joins when the best own-name place is under
# ALT_JOIN_POPULATION people and it has ALT_JOIN_RATIO× as many (Sapa, Solo,
# Bâle); a bigger own-name place keeps alternates out (Olbia).
ALT_JOIN_POPULATION = 20_000
ALT_JOIN_RATIO = 10
# ... and only an alternate-name place this big (Placencia, Belize is not
# Piacenza's "Placencia"; Samaná is not Samana, Punjab)
ALT_JOIN_MIN_POPULATION = 150_000
# R1: an airport-name match never drops a place this big.
R1_NEVER_DROP_POPULATION = 40_000
# A town scoring at least 1/20 of a same-named division's top place keeps
# the division out ("Canterbury" is the English city, not New Zealand's
# region; "Florida", Uruguay is far smaller than Florida's Jacksonville).
DIVISION_BLOCK_RATIO = 20
# The winner needs this many times the score of the next candidate.
DOMINANCE = 3.0


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
    division: bool = False  # stands for a first-level division ("Florida")
    lat: float | None = None
    lng: float | None = None


@functools.cache
def country_names() -> dict[str, str]:
    """Folded country name or alias → ISO code: every country in the
    committed country list (also those with no airport: Andorra), the
    dataset's curated spellings, and the aliases."""
    from .seed_airports import PLACE_DATA_DIR

    table: dict[str, str] = {}
    with open(PLACE_DATA_DIR / "countries.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            table[fold_place(row["name"])] = row["code"]
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
    for variant in saint_variants(stated):
        if variant in country_names():
            codes.add(country_names()[variant])
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
    """A curated island / destination / region for the folded name, unless
    a stated country names another country."""
    # the name, then its St / Saint spellings — except listed names ("Saint
    # John" is the New Brunswick city, not St John, USVI)
    tables = (ISLAND_AIRPORTS, DESTINATION_AIRPORTS, REGION_HINTS)
    spellings = [name]
    if name not in SAINT_EXCEPTIONS:
        spellings += sorted(saint_variants(name) - {name})
    hint = next((table[n] for n in spellings for table in tables if n in table), None)
    if not hint:  # any affix form of a hinted name ("Isla de Margarita")
        stripped = _stripped_hints()
        hint = next((stripped[n] for n in spellings if n in stripped), None)
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
    prefix = CODE_PREFIX_RE.match(text)
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
    for segment in stated:
        if found[segment] or stated_countries(segment) or stated_region(segment):
            continue
        # "Newfoundland" → "Newfoundland and Labrador" (word-boundary prefix)
        for row in conn.execute(
            "SELECT code FROM admin1 WHERE folded_name >= ? AND folded_name < ?",
            (segment + " ", segment + " \uffff"),
        ):
            cc, _, admin = row["code"].partition(".")
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


def _single_reading(meanings: list[_Stated], own: list[Place]) -> list[_Stated]:
    """A stated code with several readings ("CA": Canada or California;
    "MH": Marshall Islands or Maharashtra) keeps them all, unless the city
    has own-name places under one reading only: then that reading wins
    ("Ontario, CA" → Ontario, California, not the province)."""
    narrowed = []
    for m in meanings:
        readings = [_Stated(frozenset({c}), frozenset()) for c in m.countries]
        readings += [_Stated(frozenset(), frozenset({a})) for a in m.admin1]
        hits = [
            r for r in readings if any(r.admits(p.country_code, p.admin1) for p in own)
        ]
        narrowed.append(hits[0] if len(readings) > 1 and len(hits) == 1 else m)
    return narrowed


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


def _name_candidates(
    conn: sqlite3.Connection, names: list[str]
) -> tuple[list[Place], list[Place]]:
    """(places with this own name, places with it as an alternate name);
    population-0 places never count."""
    rows = conn.execute(
        f"SELECT n.tier, n.name_folded, {_PLACE_COLUMNS} FROM place_names n "
        "JOIN places p ON p.geonameid = n.geonameid "
        f"WHERE n.name_folded IN ({','.join('?' * len(names))}) "
        "AND p.population > 0",
        names,
    ).fetchall()
    own: dict[int, Place] = {}
    alt: dict[int, Place] = {}
    for row in rows:
        if row["tier"] == 0:
            own[row["geonameid"]] = _row_place(row, row["score"])
        elif len(row["name_folded"]) >= MIN_ALT_NAME_LENGTH:
            alt[row["geonameid"]] = _row_place(row, row["score"], True)
    return list(own.values()), [p for g, p in alt.items() if g not in own]


def _top_place(conn: sqlite3.Connection, where: str, params: list) -> list[Place]:
    rows = conn.execute(
        f"SELECT {_PLACE_COLUMNS} FROM places p WHERE {where} "
        "AND p.population > 0 ORDER BY p.score DESC LIMIT 2",
        params,
    ).fetchall()
    return [_row_place(r, r["score"]) for r in rows]


def _division_candidates(conn: sqlite3.Connection, names: list[str]) -> list[Place]:
    """First-level divisions with one of these names ("Florida", "Scotland",
    "Andalusia") as candidates: each stands for its top place, scored as
    that place, so it competes with towns of the same name."""
    rows = conn.execute(
        f"SELECT code FROM admin1 WHERE folded_name IN ({','.join('?' * len(names))})",
        names,
    ).fetchall()
    found = []
    for row in rows:
        cc, _, admin = row["code"].partition(".")
        top = _top_place(conn, "p.country_code = ? AND p.admin1 = ?", [cc, admin])
        if top:  # the division stands for its top place (ruling I1)
            found.append(replace(top[0], division=True))
    return found


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
        and not p.division
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


def _country_alone(city: str) -> str | None:
    """The ISO code of a country typed alone, by name, alias or a St /
    Saint form ("St Lucia")."""
    for variant in sorted(saint_variants(city)):
        if variant in country_names():
            return country_names()[variant]
    return None


def _exonym(conn: sqlite3.Connection, city: str) -> Place | str | None:
    """The place an exonym means (``EXONYMS``), "ambiguous", or None."""
    for variant in sorted(saint_variants(city)):
        target = EXONYMS.get(variant)
        if target == "ambiguous":
            return "ambiguous"
        if target is not None:
            rows = conn.execute(
                f"SELECT {_PLACE_COLUMNS} FROM places p WHERE p.geonameid = ?",
                (target,),
            ).fetchall()
            return _row_place(rows[0], rows[0]["score"]) if rows else None
    return None


# per DB file (tests switch DBs): path → (name keys, airport info)
_AIRPORT_NAME_INDEX: dict[str, tuple[dict[str, tuple[str, ...]], dict[str, tuple]]] = {}
# "Lerwick / Tingwall Airport", "Bohol–Panglao International": whole parts
_NAME_PARTS_RE = re.compile(r"\s*[/–—-]\s*")


def _airport_names(
    conn: sqlite3.Connection | None = None,
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple]]:
    """Scheduled dataset airports by WHOLE folded name without generic words
    ("La Palma Airport" → "la palma"; each "/"- or dash-separated part counts
    on its own), biggest type first, and code → (country, folded display
    city, folded name, type_rank). Built once from the seeded airports
    table (warmed at startup)."""
    from .database import _db_path

    db = str(_db_path())
    if db in _AIRPORT_NAME_INDEX:
        return _AIRPORT_NAME_INDEX[db]
    if conn is None:
        with get_connection() as own:
            return _airport_names(own)
    rows = conn.execute(
        "SELECT iata_code, name, city, country_code, type_rank FROM airports"
        " WHERE scheduled = 1 AND type_rank IS NOT NULL"
        " ORDER BY type_rank, iata_code"
    ).fetchall()
    keys: dict[str, list[str]] = {}
    info: dict[str, tuple] = {}
    for r in rows:
        info[r["iata_code"]] = (
            r["country_code"],
            fold_place(r["city"]),
            fold_place(r["name"]),
            r["type_rank"],
        )
        for part in {r["name"], *_NAME_PARTS_RE.split(r["name"])}:
            words = re.sub(r"[^\w ]", " ", fold_place(part)).split()
            key = " ".join(w for w in words if w not in AIRPORT_NAME_WORDS)
            # no fragments or generic words ("Tête-à-la-Baleine" is not "a")
            if len(key) < 4 or key in GENERIC_PLACE_WORDS:
                continue
            if r["iata_code"] not in keys.get(key, ()):
                keys.setdefault(key, []).append(r["iata_code"])
    _AIRPORT_NAME_INDEX[db] = ({k: tuple(v) for k, v in keys.items()}, info)
    return _AIRPORT_NAME_INDEX[db]


def warm(conn: sqlite3.Connection | None = None) -> None:
    """Build the in-memory airport-name index now (startup), not on the
    first request; call again after a reseed."""
    _AIRPORT_NAME_INDEX.clear()
    _airport_names(conn)


def _airport_name_candidate(
    city: str, stated: list[str], meanings: list["_Stated"]
) -> Place | None:
    """R1: scheduled airports named so, in one country (and any stated
    country), as a candidate place."""
    names, info = _airport_names()
    codes = [
        c
        for c in names.get(city, ())
        if all(
            info[c][0] in m.countries or any(cc == info[c][0] for cc, _ in m.admin1)
            for m in meanings
        )
    ]
    if codes:  # the biggest type only (SPC, not Panama's small La Palma)
        best = min(info[c][3] for c in codes)
        codes = [c for c in codes if info[c][3] == best]
    countries = {info[c][0] for c in codes}
    if len(countries) != 1:
        return None
    return Place(name=city, country_code=countries.pop(), airports=tuple(codes[:3]))


def _is_small(named: Place) -> bool:
    """Every airport of an airport-name candidate is a small field."""
    _names, info = _airport_names()
    return all(info[c][3] >= 2 for c in named.airports)


def _weak_against_airport(place: Place, small_airport: bool = False) -> bool:
    """R1: a place an airport named like the text beats: under 15k people,
    or every airport over 100 km away ("Wagga Wagga", "Lord Howe Island",
    "Saba"-style islands whose namesakes are villages)."""
    if place.population >= R1_NEVER_DROP_POPULATION:
        return False  # "Kota" (1.0M) stays Kota whatever an airport is called
    if not place.airports:
        return True
    far = min(airport_distance_km(place, c) for c in place.airports) > CONFIDENCE_KM
    if small_airport:  # a small field (Lerwick / Tingwall) only beats a
        return far  # namesake with no airport within 100 km
    return place.population < SMALL_PLACE_POPULATION or far


def _winner(
    candidates: list[Place], curated: frozenset[str], qualified: bool = False
) -> Resolution:
    """Dominance over all candidates; when none dominates, over those with an
    airport in reach. A place under ``SMALL_PLACE_POPULATION`` wins only
    alone or in a curated country; one under ``CONFIDENCE_POPULATION`` whose
    nearest airport is over ``CONFIDENCE_KM`` away only alone with a stated
    qualifier."""
    result = _pick(candidates)
    if result.ambiguous:
        result = _pick(_reachable(candidates))
    place = result.place
    if place is None or place.country_code in curated:
        return result
    if place.population < SMALL_PLACE_POPULATION and len(candidates) > 1:
        return Resolution(None, ambiguous=True)
    if (
        place.population < CONFIDENCE_POPULATION
        and place.airports
        and not (qualified and len(candidates) == 1)
        and min(airport_distance_km(place, c) for c in place.airports) > CONFIDENCE_KM
    ):
        return Resolution(None, ambiguous=True)  # R2: a guess
    return result


def _resolve(conn: sqlite3.Connection, text: str) -> Resolution:
    city, stated, typed = _parse(_strip_known_prefix(conn, text))
    if not city:
        return Resolution(None)
    hint = _hint(city, stated, typed)
    if hint:
        return Resolution(hint)
    meanings = _stated_meanings(conn, stated) if stated else []

    def admitted(places: list[Place]) -> list[Place]:
        return [
            p
            for p in places
            if all(m.admits(p.country_code, p.admin1) for m in meanings)
        ]

    exonym = _exonym(conn, city)
    if exonym == "ambiguous" and not stated:
        return Resolution(None, ambiguous=True)
    if isinstance(exonym, Place) and admitted([exonym]):
        return Resolution(exonym)
    names = _name_variants(city)
    curated = _curated_countries(names)
    country = _country_alone(city) if not stated else None
    divisions = [] if curated else _division_candidates(conn, names)
    official = city in country_names() and city not in COUNTRY_ALIASES
    if country and (official or not divisions):
        # A country typed alone → its highest-scoring place (the capital, or
        # the main gateway city: Istanbul, Zürich, Sydney, New York City).
        # A division wins over an alias ("Scotland" → Glasgow, not London).
        top = _top_place(conn, "p.country_code = ?", [country])
        return Resolution(top[0] if top else None)
    own, alternates = _name_candidates(conn, names)
    meanings = _single_reading(meanings, own)
    own, alternates = admitted(own), admitted(alternates)
    # alternates only when no place has the name as its own, or (R3) when
    # the own-name places are small and the alternate one far bigger
    candidates = list(own or alternates)
    biggest = max((p.population for p in own), default=0)
    if own and biggest < ALT_JOIN_POPULATION:
        candidates += [
            p
            for p in alternates
            if p.population >= ALT_JOIN_RATIO * max(biggest, 1)
            and p.population >= ALT_JOIN_MIN_POPULATION
        ]
    town = max((p.score for p in own), default=0)
    if divisions and town * DIVISION_BLOCK_RATIO >= max(d.score for d in divisions):
        divisions = []  # "Santa Fe", "Canterbury": the cities, not the regions
    known = {p.geonameid for p in candidates}
    candidates += [d for d in admitted(divisions) if d.geonameid not in known]
    named = _airport_name_candidate(city, stated, meanings)
    if named is not None:
        strong = [
            p
            for p in candidates
            if p.division
            or p.country_code in curated
            or not _weak_against_airport(p, small_airport=_is_small(named))
        ]
        if not strong:
            return Resolution(named)  # R1: "Wagga Wagga", "Lord Howe Island"
        candidates = strong
    if meanings and not candidates:
        return Resolution(None)  # "Berlin, Japan"
    preferred = [p for p in candidates if p.country_code in curated]
    if not preferred:
        return _winner(candidates, curated, bool(stated))
    result = _winner(preferred, curated, bool(stated))
    if result.place and _bigger_namesake(result.place, _reachable(candidates)):
        return Resolution(None, ambiguous=True, contested=True)
    return result


def resolve_place(text: str, conn: sqlite3.Connection | None = None) -> Place | None:
    """The place a typed text names, or None when unknown or ambiguous.

    1. A curated island / destination ("Sicily", "Machu Picchu") wins.
    2. A country typed alone ("Japan", "St Lucia") → its highest-scoring
       place; an alias that is also a division name ("Scotland") is the
       division.
    3. ``EXONYMS`` ("Cologne" → Köln, "Odessa" → ambiguous). Candidates:
       places whose own name (folded, with its St / Saint spellings) is the
       city; places with it as an alternate name only when there are none;
       population-0 places never count. Unless a curated city has the
       name, first-level divisions so named join as their top place
       ("Florida" → Florida's top place, not Florida, Uruguay).
    4. Stated segments filter them: a country (name, alias, ISO code), a
       region code (US / CA / AU / BR) or any first-level division name
       ("Bavaria", "Ontario", "England"); every reading counts ("CA":
       Canada or California). A stated country with no candidate → None.
    5. Curated airports' cities pick the country when candidates exist
       there, unless a bigger own-name namesake elsewhere is within the
       dominance window ("Valencia": Spain or Venezuela → None).
    6. Winner: ``DOMINANCE`` × the next candidate's score (among those
       with an airport in reach when none dominates), else None
       ("Springfield", "San Jose"); a place under 15k people wins only
       alone or in a curated country ("Praslin" without its hint).
    """
    return resolve(text, conn).place


# Generic affixes around a name ("Zanzibar Island", "Isla de Margarita",
# "Banff National Park", "Tokyo city"), tried only when the text as typed
# names nothing.
_AFFIX_SUFFIXES = (
    " islands",
    " island",
    " national park",
    " np",
    " peninsula",
    " city",
)
_AFFIX_PREFIXES = ("isla de ", "ile de ", "city of ")


def _strip_affixes(folded: str) -> str:
    for suffix in _AFFIX_SUFFIXES:
        if folded.endswith(suffix) and len(folded) > len(suffix):
            return folded[: -len(suffix)]
    for prefix in _AFFIX_PREFIXES:
        if folded.startswith(prefix) and len(folded) > len(prefix):
            return folded[len(prefix) :]
    return folded


@functools.cache
def _stripped_hints() -> dict[str, tuple[str, tuple[str, ...]]]:
    """Hints by their affix-free key ("margarita island" → "margarita")."""
    table = {}
    for hints in (REGION_HINTS, DESTINATION_AIRPORTS, ISLAND_AIRPORTS):
        for key, hint in hints.items():
            stripped = _strip_affixes(key)
            if stripped != key:
                table[stripped] = hint
    return table


# Affixes after which any place may answer ("Tokyo city"); after the others
# ("Arches National Park", "Pemba Island") only a hint or exonym may, never
# a namesake town.
_PLACE_AFFIXES = (" city", "city of ")


def _affix_variants(text: str) -> list[tuple[str, bool]]:
    """The text with a generic affix removed from its city segment, and
    whether an ordinary place may answer for it."""
    city, _, rest = text.partition(",")
    folded = fold_place(city)
    variants = []
    for suffix in _AFFIX_SUFFIXES:
        if folded.endswith(suffix) and len(folded) > len(suffix):
            variants.append((folded[: -len(suffix)], suffix in _PLACE_AFFIXES))
    for prefix in _AFFIX_PREFIXES:
        if folded.startswith(prefix) and len(folded) > len(prefix):
            variants.append((folded[len(prefix) :], prefix in _PLACE_AFFIXES))
    return [(v + ("," + rest if rest else ""), ok) for v, ok in variants]


def no_comma_readings(text: str) -> list[str]:
    """ "City Country" / "City ST" typed without a comma ("Berlin Germany",
    "Chicago IL", "Sydney Nova Scotia") → "City, Qualifier" readings, the
    longest qualifier first; only when the trailing words name a country,
    alias or region."""
    if "," in text:
        return []
    words = text.split()
    readings = []
    for k in (3, 2, 1):
        if len(words) <= k:
            continue
        tail = fold_place(" ".join(words[-k:]))
        if stated_countries(tail) or stated_region(tail):
            readings.append(" ".join(words[:-k]) + ", " + " ".join(words[-k:]))
    return readings


def _resolve_any(conn: sqlite3.Connection, text: str) -> Resolution:
    """The text as typed; when it names nothing, without a generic affix,
    then read "City Qualifier" as "City, Qualifier"."""
    result = _resolve(conn, text)
    if result.place or result.ambiguous:
        return result
    for variant, places_too in _affix_variants(text) + [
        (r, True) for r in no_comma_readings(text)
    ]:
        retry = _resolve(conn, variant)
        if not (retry.place or retry.ambiguous):
            continue
        if places_too or (retry.place and retry.place.geonameid is None):
            return retry
        if retry.place and _exonym(conn, fold_place(variant.split(",")[0])):
            return retry  # an exonym under the affix
    return result


def names_something_as_typed(text: str) -> bool:
    """The text resolves (or is ambiguous) without affix or comma rewrites."""
    try:
        with get_connection() as conn:
            result = _resolve(conn, text)
    except sqlite3.Error:
        return False
    return bool(result.place or result.ambiguous)


def resolve(text: str, conn: sqlite3.Connection | None = None) -> Resolution:
    """``resolve_place`` with the reason when there is no place."""
    if not text or not text.strip():
        return Resolution(None)
    try:
        if conn is not None:
            return _resolve_any(conn, text)
        with get_connection() as own:
            return _resolve_any(own, text)
    except sqlite3.Error as exc:  # tables missing (unseeded DB) → unresolved
        logger.debug("Place resolution failed for %r: %s", text, exc)
        return Resolution(None)
