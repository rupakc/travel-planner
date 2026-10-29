"""Build the committed airport / place data files from OurAirports and GeoNames.

Offline tool, run by hand when refreshing the snapshot; never at app runtime.
Standard library only, deterministic output (two runs give identical bytes).
The source files are untrusted data: they are only parsed as CSV / text.

    python3 -I backend/scripts/build_place_data.py \\
        --ourairports DIR --geonames-cities FILE --geonames-admin1 FILE \\
        --out backend/app/db/data > conflicts.txt

Outputs ``airports.csv``, ``places.csv.gz`` and ``admin1.csv`` in ``--out``;
the conflict report goes to stdout. See ``backend/app/db/data/README.md``.
"""

import argparse
import csv
import gzip
import io
import math
import re
import sys
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# The generator runs isolated (python3 -I), so put the backend package root on
# the path explicitly to share the runtime's fold_place and the curated list.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.places import (  # noqa: E402
    NEVER_LINK,
    fold_place,
    is_own_airport,
    words_in,
)

TYPE_RANK = {"large_airport": 0, "medium_airport": 1, "small_airport": 2}
OTHER_TYPE_RANK = 9
EXCLUDED_FEATURE_CODES = frozenset({"PPLX", "PPLH", "PPLQ", "PPLW", "PPLCH"})

# Linking reach (km) per airport type rank.
LARGE_REACH_KM = 80
LARGE_REACH_BIG_CITY_KM = 100  # places with population ≥ 1M
BIG_CITY_POPULATION = 1_000_000
MEDIUM_REACH_KM = 50
SMALL_REACH_KM = 30
SAME_COUNTRY_FALLBACK_KM = 200
FALLBACK_KM = 150
MAX_LINKS = 3
MAX_FALLBACK_LINKS = 2
IN_REACH_TYPE_FACTOR = {0: 0.3, 1: 1.0, 2: 1.0}  # distance multipliers
CURATED_HUB_FACTOR = 0.8  # a curated large airport at 4/5 of that
FALLBACK_LARGE_FACTOR = 0.75  # a large fallback airport counts at 3/4 distance
ADMIN1_TIE_RATIO = 1.25
ADMIN1_PROXY_KM = 50  # an airport's admin1 = that of the nearest place within

# Display-city chain distances (km).
DISPLAY_NAME_MATCH_KM = 40
DISPLAY_FIRST_LINK_KM = 40
DISPLAY_NEAREST_KM = 15
DISPLAY_SEARCH_KM = 50

_MILITARY_RE = re.compile(r"\b(air ?base|air force (base|station)|air station)\b")
_ADMIN_SUFFIX_RE = re.compile(r"-(si|shi|gun|ku|cho|machi|mura)$", re.IGNORECASE)
_AIRPORT_WORDS = frozenset({"airport", "international", "aerodrome", "airfield"})

ALT_NAMES_MIN_POPULATION = 15_000
ALT_NAME_MAX_LEN = 40

_EARTH_RADIUS_KM = 6371.0088
_KM_PER_DEG_LAT = 110.5  # a little under the true minimum, so cells over-cover

AIRPORT_COLUMNS = [
    "iata",
    "icao",
    "name",
    "city",
    "country",
    "country_code",
    "region",
    "type_rank",
    "scheduled",
    "lat",
    "lng",
]
PLACE_COLUMNS = [
    "geonameid",
    "name",
    "country_code",
    "admin1",
    "population",
    "score",
    "lat",
    "lng",
    "airports",
    "alt_names",
    "ascii",
]
ADMIN1_COLUMNS = ["code", "name", "folded_name"]


# ── Small pure helpers ─────────────────────────────────────────────────────


def clean_municipality(text: str) -> str:
    """The town part of an OurAirports municipality: text before the first
    "(" or ","; for "A/B" keep "A" ("Ferno (VA)" → "Ferno")."""
    for sep in ("(", ",", "/"):
        text = text.split(sep, 1)[0]
    return " ".join(text.split())


def notability_score(population: int, alt_name_count: int, feature_code: str) -> int:
    """population × (alternate_name_count + 1)² × (3 for a capital)."""
    capital = 3 if feature_code == "PPLC" else 1
    return population * (alt_name_count + 1) ** 2 * capital


# Non-letters an alternate name may contain: spaces, apostrophes, dashes, dots.
_NAME_PUNCTUATION = frozenset(" '’‘ʼʻ`-–—.·")


def is_latin(text: str) -> bool:
    """A plain Latin-script name: Latin letters (with accents), spaces,
    apostrophes, dashes and dots only — no digits, brackets or symbols."""
    for ch in text:
        if ch.isalpha():
            if not unicodedata.name(ch, "").startswith("LATIN"):
                return False
        elif not (unicodedata.combining(ch) or ch in _NAME_PUNCTUATION):
            return False
    return True


def _is_code(text: str) -> bool:
    return len(text) <= 4 and text.isupper()


def _is_url(text: str) -> bool:
    lowered = text.lower()
    return "://" in lowered or lowered.startswith(("http", "www."))


def filter_alt_names(raw: str, own_folded: str) -> list[str]:
    """GeoNames' comma-joined alternate names, kept when plain Latin-script
    (see ``is_latin``), ≤ 40 characters and not a URL or code; folded,
    de-duplicated, sorted and without the place's own folded name."""
    kept = set()
    for name in raw.split(","):
        name = name.strip()
        if (
            not name
            or len(name) > ALT_NAME_MAX_LEN
            or _is_url(name)
            or _is_code(name)
            or not is_latin(name)
        ):
            continue
        folded = fold_place(name)
        if folded and folded != own_folded:
            kept.add(folded)
    return sorted(kept)


def _raw_alt_count(raw: str) -> int:
    return sum(1 for name in raw.split(",") if name.strip())


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle (haversine) distance."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


# ── Spatial index ──────────────────────────────────────────────────────────


class GeoIndex:
    """Items with ``lat``/``lng`` bucketed in 1° cells for radius queries."""

    def __init__(self, items, key):
        self._key = key
        self._cells: dict[tuple[int, int], list] = defaultdict(list)
        for item in items:
            self._cells[(math.floor(item.lat), math.floor(item.lng))].append(item)

    def within(self, lat: float, lng: float, radius_km: float):
        """(distance, item) pairs within the radius, nearest first."""
        dlat = math.ceil(radius_km / _KM_PER_DEG_LAT)
        extreme = abs(lat) + dlat + 1
        if extreme >= 89:
            lng_cells = range(-180, 180)
        else:
            dlng = math.ceil(
                radius_km / (_KM_PER_DEG_LAT * math.cos(math.radians(extreme)))
            )
            if dlng >= 180:
                lng_cells = range(-180, 180)
            else:
                base = math.floor(lng)
                lng_cells = sorted(
                    {(x + 180) % 360 - 180 for x in range(base - dlng, base + dlng + 1)}
                )
        base_lat = math.floor(lat)
        found = []
        for y in range(base_lat - dlat, base_lat + dlat + 1):
            for x in lng_cells:
                for item in self._cells.get((y, x), ()):
                    d = distance_km(lat, lng, item.lat, item.lng)
                    if d <= radius_km:
                        found.append((d, item))
        found.sort(key=lambda pair: (pair[0], self._key(pair[1])))
        return found


@dataclass(frozen=True)
class LinkAirport:
    iata: str
    type_rank: int
    lat: float
    lng: float
    country_code: str = ""
    curated: bool = False
    folded_name: str = ""
    display: str = ""  # folded provisional display city
    admin1: str = ""  # GeoNames admin1 of the nearest same-country place
    military: bool = False  # an air base, linked only without civil cover


@dataclass
class Place:
    geonameid: str
    name: str
    ascii_name: str
    country_code: str
    admin1: str
    population: int
    score: int
    lat: float
    lng: float
    folded: str
    raw_alts: str = ""
    links: list = field(default_factory=list)  # [(iata, km)]
    in_reach: bool = False

    @property
    def rank(self) -> tuple:
        return (self.score, self.population, -_int(self.geonameid))


def _airport_index(airports) -> GeoIndex:
    return GeoIndex(airports, key=lambda a: a.iata)


# ── Linking ────────────────────────────────────────────────────────────────


def is_military(folded_name: str) -> bool:
    """An airport named only as an air base / air station (OurAirports marks
    some as scheduled). Joint civil fields ("Cheongju International Airport/
    Cheongju Air Base") also say "airport" and are not military."""
    return (
        _MILITARY_RE.search(folded_name) is not None
        and " airport" not in f" {folded_name}"
    )


def is_own(airport: LinkAirport, place: Place, distance: float) -> bool:
    """The airport is this place's own (``core.places.is_own_airport``)."""
    return is_own_airport(
        place.folded,
        airport.display,
        airport.folded_name,
        airport.country_code == place.country_code,
        distance,
    )


def _own_rank(airport: LinkAirport, place: Place) -> int:
    """0 when the airport is named for the place (display city or airport
    name: Treviso → TSF before VCE, Basel → BSL abroad), else 1. Own by
    distance alone (``is_own``'s 25 km clause) does not lift an airport in
    the ranking: a suburb's field must not lead its hub (Arvada: DEN, not
    BJC)."""
    named = airport.display == place.folded or words_in(
        place.folded, airport.folded_name
    )
    return 0 if named else 1


def _prefer_same_admin1(ranked: list, place: Place) -> list:
    """Swap neighbours so a same-admin1 airport goes first when the two are
    near-equal (weights within 1.25×) and in the same preference group."""
    ranked = list(ranked)
    for i in range(len(ranked) - 1):
        (ga, wa, a), (gb, wb, b) = ranked[i], ranked[i + 1]
        if (
            ga == gb
            and ga[1:2] == (1,)  # airports named for the place keep their order
            and a.admin1 != place.admin1
            and b.admin1 == place.admin1
            and wb <= ADMIN1_TIE_RATIO * wa
        ):
            ranked[i], ranked[i + 1] = ranked[i + 1], ranked[i]
    return ranked


def link_airports(
    place: Place, index: GeoIndex
) -> tuple[list[tuple[str, float]], bool]:
    """A place's airports as ([(iata, km)], in_reach).

    In reach per type: large 80 km (100 km for a 1M+ place), medium 50 km,
    small 30 km; ranked by (foreign, not named for the place, small, not
    curated (among named ones only), distance with large airports at 0.3 and
    other places' curated large ones at 0.24), ≤ 3. "Own"
    (``core.places.is_own_airport``): display city is the place, name
    contains it, or same country within 25 km. With no same-country (or own)
    airport in reach, large / medium airports within 200 km in the place's
    country come first, then the foreign ones in reach. Nothing in reach →
    large / medium within 200 km (own country) or 150 km (foreign), ranked
    by (foreign, distance, large airports at 3/4 distance), ≤ 2. Near-equal neighbours prefer the
    place's admin1. Air bases (non-curated) count only when no civil airport
    is in reach; ``NEVER_LINK`` airports never link.
    """
    nearby = index.within(place.lat, place.lng, SAME_COUNTRY_FALLBACK_KM)
    big = place.population >= BIG_CITY_POPULATION
    reach = {
        0: LARGE_REACH_BIG_CITY_KM if big else LARGE_REACH_KM,
        1: MEDIUM_REACH_KM,
        2: SMALL_REACH_KM,
    }
    in_reach = []
    fallback = []
    for d, a in nearby:
        if a.iata in NEVER_LINK:
            continue
        own_rank = _own_rank(a, place)
        foreign = a.country_code != place.country_code and not is_own(a, place, d)
        if d <= reach[a.type_rank]:
            # a large airport leads a medium one unless the medium is over
            # 3.3× nearer (Arvada: DEN before BJC; Providence: PVD before BOS)
            weight = d * IN_REACH_TYPE_FACTOR[a.type_rank]
            if a.curated and a.type_rank == 0 and own_rank:
                weight *= CURATED_HUB_FACTOR  # Makkah: JED before Ta'if
            # curated breaks ties only among airports named for the place
            # (Doha: DOH before DIA); otherwise a curated hub must not lead
            # the town's own nearer field (Providence: PVD, not BOS)
            group = (
                foreign,
                own_rank,
                a.type_rank == 2,
                own_rank == 0 and not a.curated,
            )
            in_reach.append((group, weight, a, d, weight))
        elif a.type_rank <= 1 and d <= (
            FALLBACK_KM if foreign else SAME_COUNTRY_FALLBACK_KM
        ):
            # a large airport counts at 3/4 of its distance: it leads a
            # medium one up to 1.33× nearer (Zaozhuang keeps Linyi, Plymouth
            # keeps Exeter; St Moritz / Davos → ZRH via destination hints)
            weight = d * (FALLBACK_LARGE_FACTOR if a.type_rank == 0 else 1)
            fallback.append(((foreign,), weight, a, d, weight))
    if any(not t[2].military for t in in_reach):
        in_reach = [t for t in in_reach if not t[2].military]
    if not in_reach and not fallback:
        return [], False
    if in_reach and all(t[0][0] for t in in_reach):
        # only foreign airports in reach: the same-country fallback first
        home = sorted((t for t in fallback if not t[0][0]), key=_link_key)
        pool = home[:MAX_FALLBACK_LINKS] + sorted(in_reach, key=_link_key)
        return [(t[2].iata, t[3]) for t in pool[:MAX_LINKS]], True
    pool, limit = (in_reach, MAX_LINKS) if in_reach else (fallback, MAX_FALLBACK_LINKS)
    pool.sort(key=_link_key)
    dist = {t[2].iata: t[3] for t in pool}
    ranked = _prefer_same_admin1([(g, w, a) for g, _, a, _, w in pool], place)
    return [(a.iata, dist[a.iata]) for _, _, a in ranked[:limit]], bool(in_reach)


def _link_key(t):
    return (t[0], t[1], t[2].iata)


# ── Display names ──────────────────────────────────────────────────────────


def display_name(name: str, ascii_name: str = "") -> str:
    """A place name for display: the ASCII spelling when the name has letters
    beyond Latin Extended-A (scholarly transliterations like "Marsá Maţrūḩ"),
    cut at the first comma, without a hyphenated East-Asian admin suffix
    ("Cheongju-si" → "Cheongju", "Tottori-shi" → "Tottori")."""
    if ascii_name and any(ord(ch) > 0x17F for ch in name):
        name = ascii_name
    name = " ".join(name.split(",", 1)[0].split())
    return _ADMIN_SUFFIX_RE.sub("", name) or name


def airport_name_city(name: str) -> str:
    """Last-resort display city: the airport name without generic words."""
    words = [w for w in name.split() if w.lower() not in _AIRPORT_WORDS]
    return " ".join(words) or name.strip()


# ── Source readers ─────────────────────────────────────────────────────────


def _read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _read_tsv(path: Path) -> list[list[str]]:
    with open(path, encoding="utf-8", newline="") as f:
        return [line.rstrip("\r\n").split("\t") for line in f if line.strip()]


def _int(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        return 0


def _read_places(cities_path: Path) -> list[Place]:
    places = []
    for f in _read_tsv(Path(cities_path)):
        if len(f) < 15 or f[7] in EXCLUDED_FEATURE_CODES:
            continue
        population = _int(f[14])
        places.append(
            Place(
                geonameid=f[0],
                name=f[1],
                ascii_name=f[2],
                country_code=f[8],
                admin1=f[10],
                population=population,
                score=notability_score(population, _raw_alt_count(f[3]), f[7]),
                lat=float(f[4]),
                lng=float(f[5]),
                folded=fold_place(f[1]),
                raw_alts=f[3],
            )
        )
    return places


# ── Build ──────────────────────────────────────────────────────────────────


@dataclass
class BuildResult:
    airports: dict[str, dict] = field(default_factory=dict)
    places: dict[str, dict] = field(default_factory=dict)
    admin1: list[tuple[str, str, str]] = field(default_factory=list)
    report: list[str] = field(default_factory=list)


def _curated_by_code(curated) -> dict[str, tuple]:
    """Curated rows keyed by IATA code; the first occurrence wins."""
    by_code: dict[str, tuple] = {}
    for row in curated:
        by_code.setdefault(row[0], row)
    return by_code


def _curated_country_names(curated) -> dict[str, str]:
    """ISO code → the curated spelling of the country (first occurrence)."""
    names: dict[str, str] = {}
    for row in curated:
        if row[5]:
            names.setdefault(row[5], row[4])
    return names


def _best(candidates):
    """The highest-ranked place of an iterable, or None."""
    return max(candidates, key=lambda p: p.rank, default=None)


# "Dane County Regional": a place named only as the county / district
# the airport is named after is not its city.
_DIVISION_WORDS = ("county", "parish", "province", "district", "region")


def _names_town(place: Place, folded_airport_name: str) -> bool:
    return words_in(place.folded, folded_airport_name) and not any(
        words_in(f"{place.folded} {w}", folded_airport_name) for w in _DIVISION_WORDS
    )


def _computed_city(a: dict, places_near, first_link_places, municipality: str):
    """Display city chain for one airport (curated aside) as (city, rule)."""
    same = [(d, p) for d, p in places_near if p.country_code == a["country_code"]]
    folded_name = fold_place(a["name"])
    steps = (
        ("name", lambda: _best(
            p for d, p in same if d <= DISPLAY_NAME_MATCH_KM
            and _names_town(p, folded_name)
        )),
        ("first-link", lambda: _best(
            p for d, p in same if d <= DISPLAY_FIRST_LINK_KM
            and p.geonameid in first_link_places
        )),
        ("nearest", lambda: next(
            (p for d, p in same if d <= DISPLAY_NEAREST_KM), None
        )),
    )  # fmt: skip
    for rule, pick in steps:
        place = pick()
        if place:
            return display_name(place.name, place.ascii_name), rule
    city = display_name(clean_municipality(municipality))
    if city:
        return city, "municipality"
    return airport_name_city(a["name"]), "airport-name"


def build(oa_dir: Path, cities_path: Path, admin1_path: Path, curated) -> BuildResult:
    """Read the sources and compute every output row plus the conflict report.
    ``curated`` is ``seed_airports.AIRPORTS``-shaped: (iata, icao, name, city,
    country, country_code, lat, lng)."""
    oa_dir = Path(oa_dir)
    result = BuildResult()
    curated_rows = _curated_by_code(curated)
    curated_countries = _curated_country_names(curated)
    oa_countries = {
        r["code"]: r["name"] for r in _read_csv(oa_dir / "countries.csv") if r["code"]
    }
    oa_by_iata = {
        r["iata_code"].strip(): r
        for r in _read_csv(oa_dir / "airports.csv")
        if r["iata_code"].strip()
    }

    def country_name(code: str) -> str:
        return curated_countries.get(code) or oa_countries.get(code, code)

    # Airports: OA scheduled large/medium/small with an IATA code, plus every
    # curated code (unscheduled in OA or missing from it → scheduled=0).
    airports: dict[str, dict] = {}
    municipalities: dict[str, str] = {}
    for iata, r in oa_by_iata.items():
        scheduled = r["scheduled_service"] == "yes" and r["type"] in TYPE_RANK
        if not scheduled and iata not in curated_rows:
            continue
        airports[iata] = {
            "iata": iata,
            "icao": r["icao_code"].strip(),
            "name": r["name"].strip(),
            "city": "",
            "country": country_name(r["iso_country"]),
            "country_code": r["iso_country"],
            "region": r["iso_region"],
            "type_rank": TYPE_RANK.get(r["type"], OTHER_TYPE_RANK),
            "scheduled": 1 if scheduled else 0,
            "lat": float(r["latitude_deg"]),
            "lng": float(r["longitude_deg"]),
        }
        municipalities[iata] = r["municipality"]
    missing = []
    for iata, cur in curated_rows.items():
        if iata in airports:
            continue
        missing.append(iata)
        airports[iata] = {
            "iata": iata,
            "icao": cur[1] or "",
            "name": cur[2],
            "city": cur[3],
            "country": cur[4],
            "country_code": cur[5],
            "region": "",
            "type_rank": OTHER_TYPE_RANK,
            "scheduled": 0,
            "lat": float(cur[6]),
            "lng": float(cur[7]),
        }

    places = _read_places(cities_path)
    place_index = GeoIndex(places, key=lambda p: _int(p.geonameid))
    near = {
        iata: place_index.within(a["lat"], a["lng"], DISPLAY_SEARCH_KM)
        for iata, a in airports.items()
    }

    # Airports that places link to: scheduled ones; non-curated air bases are
    # marked and only linked when no civil airport is in reach. A provisional display city (curated, else the display chain
    # without its link-dependent step) marks an airport as a place's own
    # ("Basel" → BSL, "Bol" → BWK).
    linkable = []
    for iata, a in airports.items():
        folded_name = fold_place(a["name"])
        if not a["scheduled"]:
            continue
        same = [(d, p) for d, p in near[iata] if p.country_code == a["country_code"]]
        if iata in curated_rows:
            display = fold_place(curated_rows[iata][3])
        else:  # the display chain without its link-dependent step
            city, _ = _computed_city(a, near[iata], set(), municipalities[iata])
            display = fold_place(city)
        admin1 = same[0][1].admin1 if same and same[0][0] <= ADMIN1_PROXY_KM else ""
        linkable.append(
            LinkAirport(
                iata,
                a["type_rank"],
                a["lat"],
                a["lng"],
                a["country_code"],
                iata in curated_rows,
                folded_name,
                display,
                admin1,
                iata not in curated_rows and is_military(folded_name),
            )
        )
    index = _airport_index(linkable)

    first_link_places: dict[str, set[str]] = defaultdict(set)
    for place in places:
        place.links, place.in_reach = link_airports(place, index)
        if place.in_reach and place.links:
            first_link_places[place.links[0][0]].add(place.geonameid)
        own = place.folded
        alts = (
            filter_alt_names(place.raw_alts, own)
            if place.population >= ALT_NAMES_MIN_POPULATION
            else []
        )
        # The ASCII spelling has its own column (loaded with the name).
        alts = [alt for alt in alts if alt != fold_place(place.ascii_name)]
        result.places[place.geonameid] = {
            "geonameid": place.geonameid,
            "name": place.name,
            "country_code": place.country_code,
            "admin1": place.admin1,
            "population": place.population,
            "score": place.score,
            "lat": place.lat,
            "lng": place.lng,
            "airports": [iata for iata, _ in place.links],
            "alt_names": alts,
            "ascii": place.ascii_name,
        }

    # Display city: curated, else the rule chain (never empty).
    computed: dict[str, tuple[str, str]] = {}
    fallback_large = []
    for iata, a in airports.items():
        computed[iata] = _computed_city(
            a,
            near[iata],
            first_link_places.get(iata, set()),
            municipalities.get(iata, ""),
        )
        cur = curated_rows.get(iata)
        if cur:
            a["city"] = cur[3]
        else:
            a["city"] = computed[iata][0]
            if a["type_rank"] == 0 and computed[iata][1] in (
                "municipality",
                "airport-name",
            ):
                fallback_large.append(iata)
    result.airports = dict(sorted(airports.items()))
    result.places = dict(sorted(result.places.items(), key=lambda kv: _int(kv[0])))

    result.admin1 = sorted(
        (f[0], f[1], fold_place(f[1])) for f in _read_tsv(Path(admin1_path)) if f[0]
    )
    result.report = _conflict_report(
        result,
        curated_rows,
        oa_by_iata,
        missing,
        fallback_large,
        computed,
        municipalities,
    )
    return result


def _conflict_report(
    result, curated_rows, oa_by_iata, missing, fallback_large, computed, munis
):
    lines = []
    unscheduled = sorted(
        iata
        for iata in curated_rows
        if iata not in missing and not result.airports[iata]["scheduled"]
    )
    lines.append(f"## Curated codes missing from OurAirports ({len(missing)})")
    for iata in sorted(missing):
        cur = curated_rows[iata]
        lines.append(f"{iata}  curated: {cur[2]}, {cur[3]}, {cur[4]}")
    lines.append("")
    lines.append(f"## Curated codes not scheduled in OurAirports ({len(unscheduled)})")
    for iata in unscheduled:
        r = oa_by_iata[iata]
        lines.append(
            f"{iata}  OA: {r['type']} scheduled_service={r['scheduled_service']} "
            f"{r['name']} ({r['municipality']}); curated city {curated_rows[iata][3]}"
        )
    lines.append("")
    mismatched = sorted(
        iata
        for iata, cur in curated_rows.items()
        if iata in oa_by_iata and oa_by_iata[iata]["iso_country"] != cur[5]
    )
    lines.append(f"## Curated vs OA country mismatches ({len(mismatched)})")
    for iata in mismatched:
        cur = curated_rows[iata]
        lines.append(
            f"{iata}  curated {cur[5]} ({cur[4]}) vs OA {oa_by_iata[iata]['iso_country']}"
        )
    lines.append("")
    far = []
    for iata, cur in sorted(curated_rows.items()):
        if iata in oa_by_iata:
            r = oa_by_iata[iata]
            d = distance_km(
                float(cur[6]),
                float(cur[7]),
                float(r["latitude_deg"]),
                float(r["longitude_deg"]),
            )
            if d > 25:
                far.append(f"{iata}  {d:.0f} km  curated {cur[2]} vs OA {r['name']}")
    lines.append(f"## Curated coordinates > 25 km from OA ({len(far)})")
    lines.extend(far)
    lines.append("")
    lines.append(
        f"## Large airports whose display city fell back to the municipality "
        f"or the airport name "
        f"({len(fallback_large)})"
    )
    for iata in sorted(fallback_large):
        a = result.airports[iata]
        lines.append(
            f"{iata}  {a['name']} → {a['city']!r} (municipality {munis[iata]!r}, "
            f"{a['country_code']})"
        )
    lines.append("")
    differs = []
    for iata, cur in sorted(curated_rows.items()):
        city, rule = computed[iata]
        if fold_place(city) != fold_place(cur[3]):
            differs.append(f"{iata}  curated {cur[3]!r} vs computed {city!r} ({rule})")
    lines.append(
        f"## Curated display city differs from the computed one ({len(differs)}, "
        "informational; curated wins)"
    )
    lines.extend(differs)
    return lines


# ── Output ─────────────────────────────────────────────────────────────────


def _coord(value: float) -> str:
    return f"{value:.5f}"


def _csv_text(header: list[str], rows) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def write_outputs(result: BuildResult, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    airports = _csv_text(
        AIRPORT_COLUMNS,
        (
            [
                a["iata"],
                a["icao"],
                a["name"],
                a["city"],
                a["country"],
                a["country_code"],
                a["region"],
                a["type_rank"],
                a["scheduled"],
                _coord(a["lat"]),
                _coord(a["lng"]),
            ]
            for a in result.airports.values()
        ),
    )
    (out_dir / "airports.csv").write_bytes(airports.encode("utf-8"))
    places = _csv_text(
        PLACE_COLUMNS,
        (
            [
                p["geonameid"],
                p["name"],
                p["country_code"],
                p["admin1"],
                p["population"],
                p["score"],
                _coord(p["lat"]),
                _coord(p["lng"]),
                " ".join(p["airports"]),
                "|".join(p["alt_names"]),
                p["ascii"],
            ]
            for p in result.places.values()
        ),
    )
    with open(out_dir / "places.csv.gz", "wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
        ) as gz:
            gz.write(places.encode("utf-8"))
    admin1 = _csv_text(ADMIN1_COLUMNS, result.admin1)
    (out_dir / "admin1.csv").write_bytes(admin1.encode("utf-8"))


def _summary(result: BuildResult, seconds: float) -> list[str]:
    airports = result.airports.values()
    places = result.places.values()
    return [
        "## Summary",
        f"airports: {len(result.airports)} "
        f"(scheduled {sum(a['scheduled'] for a in airports)})",
        f"places: {len(result.places)} "
        f"(no airports {sum(1 for p in places if not p['airports'])})",
        f"alt-name pairs: {sum(len(p['alt_names']) for p in places)}",
        f"admin1: {len(result.admin1)}",
        f"generated in {seconds:.1f} s",
        "",
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ourairports", required=True, type=Path)
    parser.add_argument("--geonames-cities", required=True, type=Path)
    parser.add_argument("--geonames-admin1", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    from app.db.seed_airports import AIRPORTS

    start = time.perf_counter()
    result = build(
        args.ourairports, args.geonames_cities, args.geonames_admin1, AIRPORTS
    )
    write_outputs(result, args.out)
    seconds = time.perf_counter() - start
    print("\n".join(_summary(result, seconds) + result.report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
