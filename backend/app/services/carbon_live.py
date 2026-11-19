"""Crawler carbon data for the trip footprint (docs/Carbon-Footprint.md,
"Crawler data").

``fetch`` reads two endpoints of the crawler's read API and returns an
*overlay* for ``carbon.compute(req, live=...)``:

* ``GET /v1/carbon/factors`` (kind ``emission_factor``): the UK DESNZ
  conversion factors (``od-desnz-ghg-factors``). Used only when the crawler
  holds a factor set **newer** than the committed table's DESNZ year; each
  newer row replaces the committed row with the same publisher label (and
  unit), so a newer set changes values, never the method. Hotel-stay rows are
  matched by country and may add countries the committed table lacks.
* ``GET /v1/carbon/grid`` (``grid_ci:<ISO2>:annual:lifecycle``): a country's
  electricity carbon intensity, used for a stay in a country that has no
  hotel-stay factor at all (committed or newer), instead of the median of the
  DESNZ countries: grid g/kWh × an assumed kWh-equivalent per room-night,
  labelled ``estimate``.

Rules: ``None`` (crawler off, down, slow or nothing usable) means the
calculator answers byte for byte as it does without the crawler. Only
mergeable facts are used (open or API-terms licence, no conflict: never
share-alike). Every number taken from the crawler carries its source object
(name, link, as-of date, licence, attribution). No LLM, nothing stored.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import unicodedata

from . import crawler_client, crawler_facts

logger = logging.getLogger(__name__)

DESNZ_SOURCE = "od-desnz-ghg-factors"
# Overall budget for the crawler reads of one request (each read also has its
# own CRAWLER_TIMEOUT_S, and the breaker makes a dead crawler cost one).
FETCH_BUDGET_S = 4.0
MAX_GRID_COUNTRIES = 10
_ISO2 = re.compile(r"^[A-Z]{2}$")

# Committed ground factor key -> crawler category of the same DESNZ row
_GROUND_CATEGORY = {
    "rail_national": "rail",
    "rail_international": "rail",
    "light_rail_tram": "rail",
    "metro": "rail",
    "bus_local": "bus",
    "coach": "bus",
    "taxi_vehicle": "taxi",
    "car_average": "car",
    "ferry_foot": "ferry",
}
# Crawler reads for a newer DESNZ set: (category, activity filter)
_FACTOR_READS = (
    ("flights", None),
    ("rail", None),
    ("bus", None),
    ("taxi", None),
    ("ferry", None),
    ("accommodation", None),
    ("car", "average_car"),
)


def slug(label: str) -> str:
    """The crawler's activity slug of a publisher label (its
    ``factor_table::slug``): ASCII-folded, lower case, ``&`` → ``and``,
    apostrophes dropped, every other run of non-alphanumerics → ``_``."""
    text = unicodedata.normalize("NFKD", str(label or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("&", " and ").replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:160]


def unit_key(unit: str) -> str | None:
    """The "per …" part of a ``kg CO2e per …`` unit, normalised so the
    committed table's spelling and DESNZ's compare equal
    (``vehicle.km`` = ``km``, ``Room per night`` = ``room.night``)."""
    u = " ".join(str(unit or "").lower().split())
    if not u.startswith("kg co2e per "):
        return None
    per = u[len("kg co2e per ") :]
    per = per.replace("room per night", "room.night").replace(
        "room night", "room.night"
    )
    per = per.replace(" ", "")
    return "km" if per == "vehicle.km" else per


def _value(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) and v >= 0 else None


def _source_obj(src: dict, *, publisher=None, year=None, dataset=None) -> dict:
    """The source object of a crawler number: what the card shows next to
    it (name, link, as-of, licence, attribution)."""
    out = {
        "name": src.get("name") or dataset or src.get("source_id"),
        "publisher": publisher if isinstance(publisher, str) else None,
        "year": year,
        "url": src.get("url"),
        "as_of": src.get("as_of"),
        "licence": src.get("spdx") or src.get("licence"),
        "licence_url": src.get("licence_url"),
        "attribution": src.get("attribution"),
        "source_id": src.get("source_id"),
        "via": "crawler",
    }
    return {k: v for k, v in out.items() if v is not None}


def _item_source(item: dict, names: dict) -> dict:
    src = crawler_facts.item_source(item, names)
    lic = item.get("licence") if isinstance(item.get("licence"), dict) else {}
    if isinstance(lic.get("spdx"), str) and lic["spdx"]:
        src["spdx"] = lic["spdx"]
    return src


def _usable_factor(item: dict, names: dict, year: int) -> tuple[dict, dict] | None:
    """(data, source) of a servable, mergeable emission factor of ``year``."""
    if item.get("kind") != "emission_factor" or item.get("conflict"):
        return None
    data = item.get("data") if isinstance(item.get("data"), dict) else None
    if not data or data.get("year") != year or _value(data.get("value")) is None:
        return None
    src = _item_source(item, names)
    if not crawler_facts.mergeable(src):
        return None
    return data, src


def static_desnz_year(static: dict) -> int | None:
    years = [
        s.get("year")
        for sid, s in static.get("sources", {}).items()
        if sid.startswith("desnz_") and isinstance(s.get("year"), int)
    ]
    return max(years) if years else None


async def _newer_factors(static: dict, names_task) -> dict | None:
    """The committed factors a newer crawler DESNZ set replaces:
    ``{"year", "flight", "ground", "hotel", "sources"}``, or None."""
    base_year = static_desnz_year(static)
    probe = await crawler_client.carbon_factors(source=DESNZ_SOURCE, limit=1)
    if not probe or base_year is None:
        return None
    first = probe[0].get("data") if isinstance(probe[0].get("data"), dict) else {}
    year = first.get("year")
    if not isinstance(year, int) or isinstance(year, bool) or year <= base_year:
        return None
    pages = await asyncio.gather(
        *(
            crawler_client.carbon_factors(
                source=DESNZ_SOURCE, year=year, category=cat, activity=act, pages=4
            )
            for cat, act in _FACTOR_READS
        )
    )
    names = await names_task
    rows: list[tuple[dict, dict]] = []
    for page in pages:
        for it in page or []:
            ok = _usable_factor(it, names, year)
            if ok:
                rows.append(ok)
    if not rows:
        return None
    sid = f"crawler_desnz_{year}"
    sources: dict[str, dict] = {}
    out = {"year": year, "flight": {}, "ground": {}, "hotel": {}, "sources": sources}

    def take(entry: dict, data: dict, src: dict) -> dict:
        obj = _source_obj(
            src, publisher=data.get("publisher"), year=year, dataset=data.get("dataset")
        )
        sources.setdefault(sid, obj)
        fac = dict(entry)
        fac.update(value=float(data["value"]), source=sid, year=year)
        if isinstance(data.get("factor_id"), str):
            fac["factor_id"] = data["factor_id"]
        fac["crawler_source"] = obj
        return fac

    def match(entry: dict, category: str, basis: tuple) -> tuple[dict, dict] | None:
        want = slug(entry.get("label", ""))
        unit = unit_key(entry.get("unit", ""))
        for data, src in rows:
            if (
                data.get("category") == category
                and data.get("activity") == want
                and unit_key(data.get("unit")) == unit
                and data.get("gas_basis") in basis
            ):
                return data, src
        return None

    for key, entry in static.get("flight", {}).items():
        found = match(entry, "flights", (entry.get("basis") or "co2e_with_rf",))
        if found:
            out["flight"][key] = take(entry, *found)
    for key, entry in static.get("ground", {}).items():
        cat = _GROUND_CATEGORY.get(key)
        found = match(entry, cat, ("co2e", None)) if cat else None
        if found:
            out["ground"][key] = take(entry, *found)
    for data, src in rows:
        cc = data.get("country_code")
        if (
            data.get("category") != "accommodation"
            or not isinstance(cc, str)
            or not _ISO2.match(cc)
            or not str(data.get("activity") or "").startswith("hotel_stay")
            or unit_key(data.get("unit")) != "room.night"
            or data.get("gas_basis") not in ("co2e", None)
            or cc in out["hotel"]
        ):
            continue
        entry = static.get("hotel", {}).get("by_country", {}).get(cc) or {
            "unit": "kg CO2e per room.night",
            "label": data.get("activity_label")
            or f"Hotel stay / {data.get('geography') or cc}",
        }
        out["hotel"][cc] = take(entry, data, src)
    if not (out["flight"] or out["ground"] or out["hotel"]):
        return None
    return out


def _grid_point(points: list[dict], cc: str, names: dict) -> dict | None:
    """The newest annual life-cycle intensity of ``cc`` with a mergeable
    licence (the crawler answers newest first)."""
    for p in points:
        key = str(p.get("series_key") or "")
        if key != f"grid_ci:{cc}:annual:lifecycle":
            continue
        value = p.get("value") if isinstance(p.get("value"), dict) else {}
        g = _value(value.get("intensity_g_per_kwh"))
        if g is None or g > 2000:
            continue
        src = crawler_facts.obs_source(p, names)
        if not crawler_facts.mergeable(src):
            continue
        lic = p.get("licence") if isinstance(p.get("licence"), dict) else {}
        if isinstance(lic.get("spdx"), str) and lic["spdx"]:
            src["spdx"] = lic["spdx"]
        year = value.get("year")
        if not isinstance(year, int) or isinstance(year, bool):
            day = str(value.get("date") or p.get("observed_at") or "")[:4]
            year = int(day) if day.isdigit() else None
        obj = _source_obj(
            src,
            publisher=value.get("publisher"),
            year=year,
            dataset=value.get("dataset"),
        )
        return {"g_per_kwh": g, "year": year, "crawler_source": obj}
    return None


async def _fetch(static: dict, stay_countries) -> dict | None:
    names_task = asyncio.ensure_future(crawler_client.source_names())
    try:
        newer = await _newer_factors(static, names_task)
    except Exception:  # a mapping bug must never break the calculator
        logger.warning("carbon_live_factors_failed", exc_info=True)
        newer = None
    covered = set(static.get("hotel", {}).get("by_country", {}))
    if newer:
        covered |= set(newer["hotel"])
    missing = [
        cc
        for cc in dict.fromkeys(stay_countries or ())
        if isinstance(cc, str) and _ISO2.match(cc) and cc not in covered
    ][:MAX_GRID_COUNTRIES]
    grid: dict[str, dict] = {}
    sources: dict[str, dict] = dict(newer["sources"]) if newer else {}
    if missing:
        answers = await asyncio.gather(
            *(crawler_client.carbon_grid(cc) for cc in missing)
        )
        names = await names_task
        for cc, points in zip(missing, answers):
            pt = _grid_point(points or [], cc, names) if points else None
            if not pt:
                continue
            sid = (
                f"crawler_grid_{slug(pt['crawler_source'].get('source_id') or 'grid')}"
            )
            pt["source"] = sid
            sources.setdefault(sid, dict(pt["crawler_source"]))
            grid[cc] = pt
    if not names_task.done():
        names_task.cancel()
    if not newer and not grid:
        return None
    return {
        "year": newer["year"] if newer else None,
        "flight": newer["flight"] if newer else {},
        "ground": newer["ground"] if newer else {},
        "hotel": newer["hotel"] if newer else {},
        "grid": grid,
        "sources": sources,
    }


async def fetch(static: dict, stay_countries) -> dict | None:
    """The crawler overlay for one footprint, or None (then the answer is
    exactly the committed-table one). Never raises."""
    if not crawler_client.configured():
        return None
    try:
        return await asyncio.wait_for(_fetch(static, stay_countries), FETCH_BUDGET_S)
    except Exception:
        logger.warning("carbon_live_unavailable", exc_info=True)
        return None
