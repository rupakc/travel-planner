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

from app.core.places import fold_place  # noqa: E402

TYPE_RANK = {"large_airport": 0, "medium_airport": 1, "small_airport": 2}
OTHER_TYPE_RANK = 9
EXCLUDED_FEATURE_CODES = frozenset({"PPLX", "PPLH", "PPLQ", "PPLW", "PPLCH"})

# Linking reach (km) per airport type rank.
LARGE_REACH_KM = 80
LARGE_REACH_BIG_CITY_KM = 100  # population ≥ 1M and no large airport ≤ 50 km
BIG_CITY_POPULATION = 1_000_000
CLOSE_LARGE_KM = 50
MEDIUM_REACH_KM = 50
SMALL_REACH_KM = 30
SAME_COUNTRY_FALLBACK_KM = 200
FALLBACK_KM = 150
MAX_LINKS = 3
MAX_FALLBACK_LINKS = 2
DISPLAY_CITY_NEAR_KM = 30

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


def is_latin(text: str) -> bool:
    """Every letter in the text is a Latin-script letter."""
    return all(
        not ch.isalpha() or unicodedata.name(ch, "").startswith("LATIN") for ch in text
    )


def _is_code(text: str) -> bool:
    return len(text) <= 4 and text.isupper()


def _is_url(text: str) -> bool:
    lowered = text.lower()
    return "://" in lowered or lowered.startswith(("http", "www."))


def filter_alt_names(raw: str, own_folded: str) -> list[str]:
    """GeoNames' comma-joined alternate names, kept when Latin-script, ≤ 40
    characters and not a URL or code; folded, de-duplicated, sorted and
    without the place's own folded name."""
    kept = set()
    for name in raw.split(","):
        name = name.strip()
        if (
            not name
            or len(name) > ALT_NAME_MAX_LEN
            or "|" in name
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


# ── Airport index and linking ──────────────────────────────────────────────


@dataclass(frozen=True)
class LinkAirport:
    iata: str
    type_rank: int
    lat: float
    lng: float
    country_code: str = ""


class AirportIndex:
    """Scheduled airports bucketed in 1° cells for radius queries."""

    def __init__(self, airports: list[LinkAirport]):
        self._cells: dict[tuple[int, int], list[LinkAirport]] = defaultdict(list)
        for a in airports:
            self._cells[(math.floor(a.lat), math.floor(a.lng))].append(a)

    def within(self, lat: float, lng: float, radius_km: float):
        """(distance, airport) pairs within the radius, nearest first."""
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
                for a in self._cells.get((y, x), ()):
                    d = distance_km(lat, lng, a.lat, a.lng)
                    if d <= radius_km:
                        found.append((d, a))
        found.sort(key=lambda pair: (pair[0], pair[1].iata))
        return found


def link_airports(
    lat: float, lng: float, population: int, index: AirportIndex, country_code: str = ""
) -> list[tuple[str, float]]:
    """A place's airports as (iata, km): those in reach for their type
    (large 80 km, or 100 km for a 1M+ place with no large airport within
    50 km; medium 50 km; small 30 km), ranked by (type, distance), ≤ 3.
    None in reach → the place's own country's large/medium airports within
    200 km (≤ 2, by type then distance); else the nearest large/medium
    airports in any country within 150 km (≤ 2)."""
    nearby = index.within(lat, lng, SAME_COUNTRY_FALLBACK_KM)
    close_large = any(a.type_rank == 0 and d <= CLOSE_LARGE_KM for d, a in nearby)
    big = population >= BIG_CITY_POPULATION and not close_large
    reach = {
        0: LARGE_REACH_BIG_CITY_KM if big else LARGE_REACH_KM,
        1: MEDIUM_REACH_KM,
        2: SMALL_REACH_KM,
    }
    in_reach = sorted(
        (a.type_rank, d, a.iata) for d, a in nearby if d <= reach[a.type_rank]
    )
    if in_reach:
        return [(iata, d) for _, d, iata in in_reach[:MAX_LINKS]]
    own = sorted(
        (a.type_rank, d, a.iata)
        for d, a in nearby
        if a.type_rank <= 1 and country_code and a.country_code == country_code
    )
    if own:
        return [(iata, d) for _, d, iata in own[:MAX_FALLBACK_LINKS]]
    fallback = [(a.iata, d) for d, a in nearby if a.type_rank <= 1 and d <= FALLBACK_KM]
    return fallback[:MAX_FALLBACK_LINKS]


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

    index = AirportIndex(
        [
            LinkAirport(
                a["iata"], a["type_rank"], a["lat"], a["lng"], a["country_code"]
            )
            for a in airports.values()
            if a["scheduled"]
        ]
    )

    # Places, their links and, per airport, the best same-country place that
    # links it first (``first_place``) or links it from within 30 km
    # (``near_place``).
    airport_country = {code: a["country_code"] for code, a in airports.items()}
    first_place: dict[str, tuple[tuple, str]] = {}
    near_place: dict[str, tuple[tuple, str]] = {}
    for f in _read_tsv(Path(cities_path)):
        if len(f) < 15 or f[7] in EXCLUDED_FEATURE_CODES:
            continue
        gid, name, ascii_name, raw_alts = f[0], f[1], f[2], f[3]
        country = f[8]
        lat, lng, population = float(f[4]), float(f[5]), _int(f[14])
        score = notability_score(population, _raw_alt_count(raw_alts), f[7])
        links = link_airports(lat, lng, population, index, country)
        own_folded = fold_place(name)
        alts = (
            filter_alt_names(raw_alts, own_folded)
            if population >= ALT_NAMES_MIN_POPULATION
            else []
        )
        ascii_folded = fold_place(ascii_name)
        if ascii_folded and ascii_folded != own_folded and ascii_folded not in alts:
            alts = sorted([*alts, ascii_folded])
        result.places[gid] = {
            "geonameid": gid,
            "name": name,
            "country_code": country,
            "admin1": f[10],
            "population": population,
            "score": score,
            "lat": lat,
            "lng": lng,
            "airports": [iata for iata, _ in links],
            "alt_names": alts,
        }
        rank = (score, population, -_int(gid))
        for position, (iata, d) in enumerate(links):
            if airport_country[iata] != country:
                continue
            for table, applies in (
                (first_place, position == 0),
                (near_place, d <= DISPLAY_CITY_NEAR_KM),
            ):
                if applies and (iata not in table or rank > table[iata][0]):
                    table[iata] = (rank, name)

    # Display city: curated; else the top-scoring same-country place whose
    # first airport this is; else the top-scoring same-country place within
    # 30 km that links it; else the cleaned municipality.
    best_place = {**near_place, **first_place}
    fallback_large = []
    for iata, a in airports.items():
        cur = curated_rows.get(iata)
        if cur:
            a["city"] = cur[3]
        elif iata in best_place:
            a["city"] = best_place[iata][1]
        else:
            a["city"] = clean_municipality(municipalities.get(iata, ""))
            if a["type_rank"] == 0:
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
        best_place,
        municipalities,
    )
    return result


def _conflict_report(
    result, curated_rows, oa_by_iata, missing, fallback_large, best_place, munis
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
        computed = best_place.get(iata, (None, None))[1] or clean_municipality(
            munis.get(iata, "")
        )
        if computed and fold_place(computed) != fold_place(cur[3]):
            differs.append(f"{iata}  curated {cur[3]!r} vs computed {computed!r}")
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
