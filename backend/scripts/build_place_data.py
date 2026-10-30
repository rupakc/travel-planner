"""Build the committed airport / place data files from OurAirports and GeoNames.

Offline tool, run by hand when refreshing the snapshot; never at app runtime.
Standard library only, deterministic output (two runs give identical bytes).
The source files are untrusted data: they are only parsed as CSV / text.

    python3 -I backend/scripts/build_place_data.py \\
        --ourairports DIR --geonames-cities FILE --geonames-admin1 FILE \\
        --geonames-all allCountries.zip --out backend/app/db/data > conflicts.txt

Outputs ``airports.csv``, ``places.csv.gz``, ``admin1.csv``,
``countries.csv`` and ``features.csv.gz`` in ``--out``;
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
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# The generator runs isolated (python3 -I), so put the backend package root on
# the path explicitly to share the runtime's fold_place and the curated list.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.places import (  # noqa: E402
    AIRPORT_NAME_WORDS,
    COUNTRY_ALIASES,
    NEVER_LINK,
    QUALIFIER_COUNTRY_ALIASES,
    feature_short_names,
    fold_place,
    is_named_airport,
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
DISPLAY_ANY_LINK_RATIO = 10  # a much bigger near place linking it anywhere

_MILITARY_RE = re.compile(r"\b(air ?base|air force (base|station)|air station|afb)\b")
# Bases (not stations) never link when any civil airport is in fallback range
_AIR_BASE_RE = re.compile(r"\b(air ?base|air force base|afb)\b")
_ADMIN_SUFFIX_RE = re.compile(r"-(si|shi|gun|ku|cho|machi|mura)$", re.IGNORECASE)
_NON_WORD_RE = re.compile(r"[^\w ]")  # as in core.places.words_in

ALT_NAMES_MIN_POPULATION = 15_000
ALT_NAME_MAX_LEN = 40

_EARTH_RADIUS_KM = 6371.0088
_KM_PER_DEG_LAT = 110.5  # a little under the true minimum, so cells over-cover

# Satellite: a place whose first airport is the own airport of a place at
# least SATELLITE_OWNER_RATIO× its score within SATELLITE_KM (Peoria,
# Arizona: PHX is Phoenix's). A comparable neighbour does not make a town a
# suburb (Concord, NH flies from Manchester's MHT; Newport from Cardiff's).
SATELLITE_KM = 60
SATELLITE_OWNER_RATIO = 10
# ... and a deep suburb (satellite=2) when the owner scores this many times
# more (Pontevedra, Buenos Aires; Spain's Pontevedra is only a satellite).
SATELLITE_DEEP_RATIO = 100

# Country names from GeoNames allCountries: the political entities' names.
COUNTRY_FEATURE_CODES = frozenset(
    {"PCLI", "PCLD", "PCLF", "PCLS", "PCL", "PCLIX", "TERR"}
)
# folded letters; shorter ones are mostly noise ("pain", "some", "kili";
# "Eire" is a curated alias)
COUNTRY_NAME_MIN_LEN = 5
# A country name that is also the own name of a place this big is the place's.
COUNTRY_NAME_PLACE_POPULATION = 15_000

# Non-town features kept from allCountries (GeoNames feature codes).
FEATURE_CODES = frozenset(
    {
        "ISL", "ISLS", "ATOL",  # islands, archipelagos, atolls (not ISLT)
        "PEN",  # peninsulas
        "PRK", "RESN", "RESW", "RESF",  # parks and reserves
        "RSRT",  # resorts (GeoNames has no separate ski-area code)
        "RGN", "AREA", "CST",  # regions, areas, coasts
        "MT", "MTS", "PK", "VLC",  # mountains, ranges, peaks, volcanoes
        "VAL",  # valleys
        "LK",  # lakes
        "BCH",  # beaches
        "ANS", "RUIN", "HSTS", "MNMT",  # ancient / historical sites, monuments
        "DSRT",  # deserts
        "GRGE", "CNYN",  # gorges, canyons
        "GLCR", "CAPE", "FJD", "CAVE",  # glaciers, capes, fjords, caves
    }
)  # fmt: skip
ISLAND_CODES = frozenset({"ISL", "ISLS", "ATOL"})
# Classes admitted from notability 5 only with a name no other row has.
WEAK_CHECK_CODES = ISLAND_CODES | {"DSRT"}
# Notability = GeoNames' alternate-name count; calibrated (see the README).
# Parks, reserves, resorts, glaciers, capes, fjords, caves, islands and
# deserts are rarely translated, so they count from FEATURE_LOW_NOTABILITY.
FEATURE_MIN_NOTABILITY = 10
FEATURE_LOW_NOTABILITY = 5
FEATURE_LOW_CODES = frozenset(
    {"PRK", "RESN", "RESW", "RESF", "RSRT", "GLCR", "CAPE", "FJD", "CAVE"}
    | {"ISL", "ISLS", "ATOL", "DSRT"}  # islands and deserts too (Comino, Namib)
)
# Famous districts (Bondi, Ealing, Frankston): populated rows that are not
# places (sections of places, or seats GeoNames gives no people), with this many
# alternate names or (sections) this many people; they take the airports of
# the highest-scoring place within DISTRICT_PARENT_KM.
DISTRICT_MIN_NOTABILITY = 10
DISTRICT_MIN_POPULATION = 10_000
DISTRICT_PARENT_KM = 50
DISTRICT_EXCLUDED_CODES = frozenset({"PPLH", "PPLQ", "PPLW", "PPLCH"})
DISTRICT_SEAT_CODES = frozenset({"PPLA2", "PPLA3", "PPLA4", "PPLA5"})
# Contested district names: namesakes are other sections (PPLX; for a seat
# also other seats) farther than DISTRICT_NAMESAKE_KM, those within
# DISTRICT_NAMESAKE_MERGE_KM of each other counted once ("Centar",
# "Chinatown", "Altstadt" → None; see ``district_keeps_name``).
NAMESAKE_SEAT_CODES = frozenset({"PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC"})
DISTRICT_NAMESAKE_KM = 50
DISTRICT_NAMESAKE_MERGE_KM = 20
FEATURE_AIRPORT_KM = 250  # large / medium airports linked within
FEATURE_LARGE_FACTOR = 0.5  # a large airport ranks at half its distance
# An airport on an island: within this distance of the island's point, and
# that island is the nearest notable island point to the airport.
ISLAND_AIRPORT_KM = 50
# Rows whose primary names make a feature's alternate name ambiguous:
# populated places, administrative divisions and the listed feature codes.
SHARED_NAME_CLASSES = frozenset({"P", "A"})

COUNTRY_COLUMNS = ["code", "name", "names", "qualifier_names"]
FEATURE_COLUMNS = [
    "geonameid",
    "name",
    "ascii",
    "country_code",
    "admin1",
    "feature_code",
    "notability",
    "lat",
    "lng",
    "airports",
    "alt_names",
    "population",
    "contested",
]
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
    "satellite",
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


def _is_air_base(airport: LinkAirport) -> bool:
    return airport.military and _AIR_BASE_RE.search(airport.folded_name) is not None


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
    civil_near = any(
        not a.military
        and d <= (SAME_COUNTRY_FALLBACK_KM if a.country_code == place.country_code
                  else FALLBACK_KM)
        for d, a in nearby
    )  # fmt: skip
    if civil_near:  # Cape May: ACY, never Dover AFB
        in_reach = [t for t in in_reach if not _is_air_base(t[2])]
        fallback = [t for t in fallback if not _is_air_base(t[2])]
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
    words = [w for w in name.split() if w.lower() not in AIRPORT_NAME_WORDS]
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


def _iter_geonames_all(path: Path, keep=None):
    """Rows of GeoNames ``allCountries`` (the .zip, streamed, or its .txt)
    for which ``keep(row)`` holds; by default country entities and listed
    features."""
    wanted = COUNTRY_FEATURE_CODES | FEATURE_CODES
    keep = keep or (
        lambda f: (
            f[7] in wanted or (f[6] == "P" and f[7] not in DISTRICT_EXCLUDED_CODES)
        )
    )
    path = Path(path)

    def rows(lines):
        for line in lines:
            f = line.rstrip("\r\n").split("\t")
            if len(f) >= 15 and keep(f):
                yield f

    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            member = next(n for n in sorted(z.namelist()) if n.endswith(".txt"))
            with z.open(member) as raw:
                yield from rows(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
    else:
        with open(path, encoding="utf-8", newline="") as f:
            yield from rows(f)


@dataclass
class Feature:
    geonameid: str
    name: str
    ascii_name: str
    country_code: str
    admin1: str
    feature_code: str
    notability: int
    lat: float
    lng: float
    raw_alts: str = ""
    population: int = 0


def _country_name_candidates(rows) -> dict[str, set[str]]:
    """Folded name → ISO codes of the country entities carrying it: the
    name, the ASCII name and the Latin-script alternates (≤ 40 characters,
    ≥ 5 letters folded with a vowel — not consonant-only transliterations
    like "qndh" —, no URL, no all-caps code: "KSA", "PRC" are curated
    aliases, as ISO-3 codes would collide with airport codes)."""
    found: dict[str, set[str]] = defaultdict(set)
    for f in rows:
        for name in [f[1], f[2], *f[3].split(",")]:
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
            if len(folded.replace(" ", "")) >= COUNTRY_NAME_MIN_LEN and any(
                v in folded for v in "aeiou"
            ):
                found[folded].add(f[8])
    return found


def country_names(
    rows, official: dict[str, str], places
) -> tuple[dict, dict, list[str]]:
    """(ISO code → sorted folded country names from GeoNames, ISO code →
    qualifier-only names, the report).

    ``official`` maps the names the resolver already knows (OurAirports and
    curated spellings, aliases) to their code: those are not repeated, and
    another country's name is never taken. A name two countries carry, or
    the own name of a place with ≥ 15,000 people (Brasília's "Brasilia" for
    Brazil), is dropped and reported. The own name of a smaller place
    ("Eretria", Greece for Eritrea; "Coria", Spain for Korea) names the
    country only as a qualifier ("Asmara, Eretria"); typed alone it stays
    the town. Countries' own native names that collide are curated aliases
    (hints.json: "nederland")."""
    place_names = defaultdict(list)
    for p in places:
        for own in {p.folded, fold_place(p.ascii_name)}:
            place_names[own].append(p)
    names: dict[str, list[str]] = defaultdict(list)
    qualifiers: dict[str, list[str]] = defaultdict(list)
    shared, collisions = [], []
    for name, codes in sorted(_country_name_candidates(rows).items()):
        if name in official:
            continue
        if len(codes) > 1:
            shared.append(f"{name}  {' '.join(sorted(codes))}")
            continue
        code = next(iter(codes))
        if name in place_names:
            best = max(place_names[name], key=lambda p: p.rank)
            if best.population >= COUNTRY_NAME_PLACE_POPULATION:
                collisions.append(
                    f"{name}  {code} vs {best.name} ({best.country_code}, "
                    f"{best.population:,})"
                )
            else:
                qualifiers[code].append(name)
            continue
        names[code].append(name)
    report = [f"## Country names two countries share, dropped ({len(shared)})"]
    report += shared + [""]
    report.append(
        f"## Country names that are a 15k+ place's own name, dropped "
        f"({len(collisions)})"
    )
    report += collisions + [""]
    report.append(
        f"## Country names that are a smaller place's own name, qualifier only "
        f"({sum(len(v) for v in qualifiers.values())})"
    )
    report.append("")
    return names, qualifiers, report


def feature_threshold(feature_code: str) -> int:
    """The notability a listed feature needs (see the README calibration)."""
    if feature_code in FEATURE_LOW_CODES:
        return FEATURE_LOW_NOTABILITY
    return FEATURE_MIN_NOTABILITY


def _is_district(f: list[str], place_ids) -> bool:
    """A famous populated row that is not a place: a section of a place
    (PPLX) with ≥ 10 alternate names or ≥ 10,000 people, or an
    administrative seat with no population and ≥ 10 alternate names
    (Ealing, a London borough)."""
    if f[6] != "P" or f[7] in DISTRICT_EXCLUDED_CODES or f[0] in place_ids:
        return False
    notable = _raw_alt_count(f[3]) >= DISTRICT_MIN_NOTABILITY
    if f[7] == "PPLX":
        return notable or _int(f[14]) >= DISTRICT_MIN_POPULATION
    # an administrative seat GeoNames gives no population (a London borough)
    return notable and f[7] in DISTRICT_SEAT_CODES and _int(f[14]) == 0


def read_geonames_all(path, place_ids=frozenset()):
    """One streaming pass over allCountries: (country entity rows, notable
    listed features, famous districts)."""
    countries, notable, districts, sections = [], [], [], []
    for f in _iter_geonames_all(path):
        if f[7] in COUNTRY_FEATURE_CODES:
            countries.append(f)
            continue
        if f[6] == "P" and (f[7] == "PPLX" or f[7] in NAMESAKE_SEAT_CODES):
            sections.append(
                (f[0], f[7], float(f[4]), float(f[5]), _raw_alt_count(f[3]),
                 f[1], f[2])
            )  # fmt: skip
        notability = _raw_alt_count(f[3])
        if f[7] in FEATURE_CODES:
            if notability < feature_threshold(f[7]):
                continue
            target = notable
        elif _is_district(f, place_ids):
            target = districts
        else:
            continue
        target.append(
            Feature(
                geonameid=f[0],
                name=f[1],
                ascii_name=f[2],
                country_code=f[8],
                admin1=f[10],
                feature_code=f[7],
                notability=notability,
                lat=float(f[4]),
                lng=float(f[5]),
                raw_alts=f[3],
                population=_int(f[14]),
            )
        )
    return countries, notable, districts, sections


def district_keeps_name(k: int, b: int, t: int) -> bool:
    """A district keeps a bare name with k namesakes whose best notability
    is b, its own being t (calibrated in the final blind check)."""
    return (
        k == 0
        or (k <= 3 and t > b)
        or (k <= 8 and t >= 10 and t >= 2 * b)
        or (t >= 30 and t >= 2 * b)
    )


def contested_names(districts, sections) -> dict[str, list[str]]:
    """District id → its own folded names that are contested: other
    sections (PPLX; for a seat also other seats) carry them farther than
    50 km away, too many or too notable for the district to keep them."""
    wanted = {
        n for d in districts for n in {fold_place(d.name), fold_place(d.ascii_name)}
    }
    by_name: dict[str, list[tuple]] = defaultdict(list)
    for row in sections:
        for n in {fold_place(row[5]), fold_place(row[6])} & wanted:
            by_name[n].append(row)
    contested: dict[str, list[str]] = {}
    for d in districts:
        codes = {"PPLX"} | (NAMESAKE_SEAT_CODES if d.feature_code != "PPLX" else set())
        names = []
        for n in sorted({fold_place(d.name), fold_place(d.ascii_name)} - {""}):
            far = sorted(
                (
                    r
                    for r in by_name.get(n, ())
                    if r[0] != d.geonameid
                    and r[1] in codes
                    and distance_km(d.lat, d.lng, r[2], r[3]) > DISTRICT_NAMESAKE_KM
                ),
                key=lambda r: (-r[4], _int(r[0])),
            )
            groups: list[tuple] = []
            for r in far:
                if not any(
                    distance_km(r[2], r[3], g[2], g[3]) < DISTRICT_NAMESAKE_MERGE_KM
                    for g in groups
                ):
                    groups.append(r)
            best = max((g[4] for g in groups), default=0)
            if not district_keeps_name(len(groups), best, d.notability):
                names.append(n)
        contested[d.geonameid] = names
    return contested


def district_airports(district: Feature, place_index: GeoIndex) -> list[str]:
    """The airports of the highest-scoring place with airports within
    ``DISTRICT_PARENT_KM`` in the district's country (Bondi → Sydney's)."""
    parent = _best(
        p
        for d, p in place_index.within(district.lat, district.lng, DISTRICT_PARENT_KM)
        if p.country_code == district.country_code and p.links
    )
    return [iata for iata, _km in parent.links] if parent else []


def _first_word(folded: str) -> str:
    return folded.split(" ", 1)[0]


def shared_alt_names(path, alt_names: dict[str, list[str]]) -> dict[str, set[str]]:
    """Folded alternate name → ids of the other allCountries rows (populated
    places, divisions, listed features) whose own name it is: a second pass.
    "Blue Mountains" is Abajo Mountains' alternate and the Australian
    range's name; "El Chaltén" is Cerro Fitzroy's and the town's."""
    wanted = {alt for alts in alt_names.values() for alt in alts}
    firsts = {_first_word(alt) for alt in wanted}

    def keep(f):
        if f[6] not in SHARED_NAME_CLASSES and f[7] not in FEATURE_CODES:
            return False
        # cheap pre-check on the first word before folding
        head = f[2].lower().replace("-", " ").replace(".", " ").split(" ", 1)[0]
        return head in firsts or _first_word(fold_place(f[1])) in firsts

    holders: dict[str, set[str]] = defaultdict(set)
    for f in _iter_geonames_all(path, keep):
        for own in {fold_place(f[1]), fold_place(f[2])} & wanted:
            holders[own].add(f[0])
    return holders


def _primary_names(feature: Feature) -> set[str]:
    """A feature's folded own and ASCII names and their short forms (as the
    loader indexes them)."""
    names = {fold_place(feature.name), fold_place(feature.ascii_name)} - {""}
    return names | {s for n in names for s in feature_short_names(n)}


def island_airports(islands, airports) -> dict[str, str]:
    """Airport → the notable island it is on: the nearest notable island
    point, within ``ISLAND_AIRPORT_KM``. GeoNames has points, not outlines,
    so a big island whose point is far from its airports gets none this
    way."""
    index = GeoIndex(islands, key=lambda i: _int(i.geonameid))
    on = {}
    for a in airports:
        found = index.within(a.lat, a.lng, ISLAND_AIRPORT_KM)
        if found:
            on[a.iata] = found[0][1].geonameid
    return on


def link_feature(feature: Feature, index: GeoIndex, on_island: dict) -> list[str]:
    """A feature's airports: those on it (an island's, nearest first), then
    large / medium airports within 250 km ranked by (foreign, effective
    distance: a large airport at × 0.5), ≤ 3, so a near medium airport is
    not buried under far hubs (Florida Keys: EYW before MIA). Air bases and
    ``NEVER_LINK`` airports never link."""
    nearby = [
        (d, a)
        for d, a in index.within(feature.lat, feature.lng, FEATURE_AIRPORT_KM)
        if a.iata not in NEVER_LINK and not a.military
    ]
    own = [a.iata for d, a in nearby if on_island.get(a.iata) == feature.geonameid]
    ranked = sorted(
        ((a.country_code != feature.country_code,
          d * (FEATURE_LARGE_FACTOR if a.type_rank == 0 else 1), a.iata)
         for d, a in nearby if a.type_rank <= 1),
    )  # fmt: skip
    codes = own + [t[2] for t in ranked if t[2] not in own]
    return codes[:MAX_LINKS]


# ── Build ──────────────────────────────────────────────────────────────────


@dataclass
class BuildResult:
    airports: dict[str, dict] = field(default_factory=dict)
    places: dict[str, dict] = field(default_factory=dict)
    admin1: list[tuple[str, str, str]] = field(default_factory=list)
    countries: list[tuple[str, str, list[str], list[str]]] = field(default_factory=list)
    features: dict[str, dict] = field(default_factory=dict)
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


def _linking_place(same, first_link_places, any_link_places):
    """The best same-country place within 40 km whose first link is the
    airport; a place within 15 km linking it in any position and scoring
    ≥ 10× more wins (HLP: Jakarta, not Bekasi; EOH: Medellín)."""
    first = _best(
        p for d, p in same
        if d <= DISPLAY_FIRST_LINK_KM and p.geonameid in first_link_places
    )  # fmt: skip
    bigger = _best(
        p for d, p in same
        if d <= DISPLAY_NEAREST_KM and p.geonameid in any_link_places
    )  # fmt: skip
    if bigger and (
        first is None or bigger.score >= DISPLAY_ANY_LINK_RATIO * first.score
    ):
        return bigger
    return first


def _computed_city(
    a: dict, places_near, first_link_places, municipality: str, any_link_places=()
):
    """Display city chain for one airport (curated aside) as (city, rule)."""
    same = [(d, p) for d, p in places_near if p.country_code == a["country_code"]]
    folded_name = fold_place(a["name"])
    steps = (
        ("name", lambda: _best(
            p for d, p in same if d <= DISPLAY_NAME_MATCH_KM
            and _names_town(p, folded_name)
        )),
        ("first-link", lambda: _linking_place(
            same, first_link_places, any_link_places
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


def build(
    oa_dir: Path, cities_path: Path, admin1_path: Path, curated, all_path=None
) -> BuildResult:
    """Read the sources and compute every output row plus the conflict report.
    ``curated`` is ``seed_airports.AIRPORTS``-shaped: (iata, icao, name, city,
    country, country_code, lat, lng). ``all_path`` is GeoNames allCountries
    (.zip or .txt): country names and features; without it both are empty."""
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
    any_link_places: dict[str, set[str]] = defaultdict(set)
    for place in places:
        place.links, place.in_reach = link_airports(place, index)
        if place.in_reach and place.links:
            first_link_places[place.links[0][0]].add(place.geonameid)
            # a place linking the airport in any position (HLP is Jakarta's
            # second airport, Bekasi's first)
            for iata, _km in place.links:
                any_link_places[iata].add(place.geonameid)
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
            any_link_places.get(iata, set()),
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
    satellites = _satellites(places, airports)
    for place in places:
        result.places[place.geonameid]["satellite"] = satellites.get(place.geonameid, 0)
    result.airports = dict(sorted(airports.items()))
    result.places = dict(sorted(result.places.items(), key=lambda kv: _int(kv[0])))

    country_rows, notable, districts, sections = (
        read_geonames_all(all_path, {p.geonameid for p in places if p.population})
        if all_path
        else ([], [], [], [])
    )
    contested = contested_names(districts, sections)
    official = {fold_place(n): c for c, n in oa_countries.items()}
    official.update(
        (fold_place(a["country"]), a["country_code"]) for a in airports.values()
    )
    official.update(COUNTRY_ALIASES)
    official.update(QUALIFIER_COUNTRY_ALIASES)
    names, qualifier_names, names_report = country_names(country_rows, official, places)
    # every country, airport or not (Andorra, Liechtenstein, San Marino)
    result.countries = [
        (c, n, names.get(c, []), qualifier_names.get(c, []))
        for c, n in sorted(oa_countries.items())
    ]
    # airports sit on islands notable at the standard threshold: with the
    # lower one, islets near the coast claimed MFA (Mafia) and MHC (Chiloé)
    islands = [
        f
        for f in notable
        if f.feature_code in ISLAND_CODES and f.notability >= FEATURE_MIN_NOTABILITY
    ]
    on_island = island_airports(islands, linkable)
    linked = {}
    tagged = [(f, False) for f in notable] + [(f, True) for f in districts]
    for feature, is_district in tagged:
        if is_district:
            codes = district_airports(feature, place_index)
        else:
            codes = link_feature(feature, index, on_island)
        if not codes:
            continue
        alts = filter_alt_names(feature.raw_alts, fold_place(feature.name))
        linked[feature.geonameid] = (
            feature,
            codes,
            [alt for alt in alts if alt != fold_place(feature.ascii_name)],
        )
    # a weakly notable island or desert (5–9 alternate names) whose own or
    # short name is another row's own name is ambiguous ("Sugarloaf" Island,
    # California among the Sugarloaf mountains)
    weak_names = {
        g: sorted(_primary_names(f))
        for g, (f, _c, _a) in linked.items()
        if f.feature_code in WEAK_CHECK_CODES and f.notability < FEATURE_MIN_NOTABILITY
    }
    holders = (
        shared_alt_names(
            all_path,
            {
                g: [*alts, *weak_names.get(g, [])]
                for g, (_f, _c, alts) in linked.items()
            },
        )
        if all_path
        else {}
    )
    shared_alts = weak_dropped = 0
    for gid, (feature, codes, all_alts) in linked.items():
        if any(holders.get(n, set()) - {gid} for n in weak_names.get(gid, ())):
            weak_dropped += 1
            continue
        # an alternate that is another row's own name is ambiguous
        alts = [a for a in all_alts if not holders.get(a, set()) - {gid}]
        shared_alts += len(all_alts) - len(alts)
        result.features[feature.geonameid] = {
            "geonameid": feature.geonameid,
            "name": feature.name,
            "ascii": feature.ascii_name,
            "country_code": feature.country_code,
            "admin1": feature.admin1,
            "feature_code": feature.feature_code,
            "notability": feature.notability,
            "lat": feature.lat,
            "lng": feature.lng,
            "airports": codes,
            "alt_names": alts,
            "population": feature.population,
            "contested": contested.get(gid, []),
        }
    names_report += [
        f"## Feature alternate names that are another row's own name, dropped "
        f"({shared_alts})",
        "",
        f"## Weakly notable islands / deserts whose name another row has, "
        f"dropped ({weak_dropped})",
        "",
    ]
    result.features = dict(sorted(result.features.items(), key=lambda kv: _int(kv[0])))

    result.admin1 = sorted(
        (f[0], f[1], fold_place(f[1])) for f in _read_tsv(Path(admin1_path)) if f[0]
    )
    result.report = (
        _conflict_report(
            result,
            curated_rows,
            oa_by_iata,
            missing,
            fallback_large,
            computed,
            municipalities,
        )
        + [""]
        + names_report
    )
    return result


def _satellites(places, airports: dict[str, dict]) -> dict[str, int]:
    """Places whose first airport is not named for them but for a place
    scoring ≥ ``SATELLITE_OWNER_RATIO``× more within ``SATELLITE_KM``
    (Peoria, Arizona flies from Phoenix's PHX; Peoria, Illinois has PIA).
    Named = ``core.places.is_named_airport`` with the final display city:
    never distance alone, so a suburb next to a hub (Pontevedra, Buenos
    Aires and EZE) is a satellite too, and a town near another town's
    airport is not that town's satellite. Value 2: a deep suburb, whose
    owner scores ≥ ``SATELLITE_DEEP_RATIO``× more; 1 otherwise."""
    by_name: dict[str, list[Place]] = defaultdict(list)
    for p in places:
        by_name[p.folded].append(p)
    owners: dict[str, list[Place]] = {}

    def owners_of(iata: str) -> list[Place]:
        if iata not in owners:
            a = airports[iata]
            city, name = fold_place(a["city"]), fold_place(a["name"])
            found = {p.geonameid: p for p in by_name.get(city, ())}
            words = _NON_WORD_RE.sub(" ", name).split()
            for i in range(len(words)):  # places the airport name names
                for j in range(i + 1, len(words) + 1):
                    for p in by_name.get(" ".join(words[i:j]), ()):
                        if words_in(p.folded, name):
                            found[p.geonameid] = p
            owners[iata] = list(found.values())
        return owners[iata]

    satellites: dict[str, int] = {}
    for p in places:
        if not p.links:
            continue
        iata = p.links[0][0]
        a = airports[iata]
        if is_named_airport(p.folded, fold_place(a["city"]), fold_place(a["name"])):
            continue
        ratios = [
            q.score / max(p.score, 1)
            for q in owners_of(iata)
            if q is not p
            and q.score >= SATELLITE_OWNER_RATIO * p.score
            and distance_km(p.lat, p.lng, q.lat, q.lng) <= SATELLITE_KM
        ]
        if ratios:
            satellites[p.geonameid] = 2 if max(ratios) >= SATELLITE_DEEP_RATIO else 1
    return satellites


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


def _write_gzip(path: Path, text: str) -> None:
    """Deterministic gzip: no file name, mtime 0."""
    with open(path, "wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
        ) as gz:
            gz.write(text.encode("utf-8"))


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
                p["satellite"],
            ]
            for p in result.places.values()
        ),
    )
    _write_gzip(out_dir / "places.csv.gz", places)
    features = _csv_text(
        FEATURE_COLUMNS,
        (
            [
                f["geonameid"],
                f["name"],
                f["ascii"],
                f["country_code"],
                f["admin1"],
                f["feature_code"],
                f["notability"],
                _coord(f["lat"]),
                _coord(f["lng"]),
                " ".join(f["airports"]),
                "|".join(f["alt_names"]),
                f["population"],
                "|".join(f["contested"]),
            ]
            for f in result.features.values()
        ),
    )
    _write_gzip(out_dir / "features.csv.gz", features)
    admin1 = _csv_text(ADMIN1_COLUMNS, result.admin1)
    (out_dir / "admin1.csv").write_bytes(admin1.encode("utf-8"))
    countries = _csv_text(
        COUNTRY_COLUMNS,
        ((c, n, "|".join(names), "|".join(q)) for c, n, names, q in result.countries),
    )
    (out_dir / "countries.csv").write_bytes(countries.encode("utf-8"))


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
        f"satellites: {sum(p['satellite'] > 0 for p in places)} "
        f"(deep {sum(p['satellite'] == 2 for p in places)})",
        f"country names: {sum(len(row[2]) for row in result.countries)} "
        f"(qualifier only {sum(len(row[3]) for row in result.countries)})",
        f"features: {len(result.features)} (notability ≥ {FEATURE_MIN_NOTABILITY}, "
        f"{FEATURE_LOW_NOTABILITY} for {', '.join(sorted(FEATURE_LOW_CODES))}; "
        f"districts {sum(f['feature_code'] not in FEATURE_CODES for f in result.features.values())}; "
        f"contested names {sum(len(f['contested']) for f in result.features.values())})",
        f"generated in {seconds:.1f} s",
        "",
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ourairports", required=True, type=Path)
    parser.add_argument("--geonames-cities", required=True, type=Path)
    parser.add_argument("--geonames-admin1", required=True, type=Path)
    parser.add_argument(
        "--geonames-all", required=True, type=Path, help="allCountries.zip or .txt"
    )
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    from app.db.seed_airports import AIRPORTS

    start = time.perf_counter()
    result = build(
        args.ourairports,
        args.geonames_cities,
        args.geonames_admin1,
        AIRPORTS,
        args.geonames_all,
    )
    write_outputs(result, args.out)
    seconds = time.perf_counter() - start
    print("\n".join(_summary(result, seconds) + result.report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
