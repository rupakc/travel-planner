"""Turn extracted places into a reviewable trip preview.

Each place's city is resolved with the local place data (``resolve_place``)
to a canonical city, country, coordinates and airports. Towns within a day
trip of a bigger stop join that stop. Stops are ordered by the source's day
hints, capped at three (the busiest), and given nights by place count. With
``SERPER_KEY`` set, each place is looked up on Google Maps for its own
coordinates (``verified``); otherwise it sits at its town's centre
(``approximate``).
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field

from ..core.cache import get_cache
from ..core.config import settings
from ..core.places import fold_place
from ..db.database import lookup_city_iata
from ..db.places_db import country_display_name, country_names, resolve_place
from ..utils.geo import haversine_km, lookup_coords
from .name_match import STOP_WORDS
from .serper_places import SerperPlacesClient

logger = logging.getLogger(__name__)

MAX_DESTINATIONS = 3
MAX_SERPER_LOOKUPS = 25
SERPER_CONCURRENCY = 5
DAY_TRIP_KM = 45.0
SERPER_MAX_KM = 60.0
PLACES_PER_DAY = 4
MIN_DAYS, MAX_DAYS = 3, 14
# Hotels and transport don't fill a day of sightseeing
_NOT_A_VISIT = {"stay", "transport"}


@dataclass
class _City:
    name: str
    country_code: str
    country: str
    lat: float | None
    lng: float | None
    airports: list[str]
    population: int

    @property
    def key(self) -> tuple[str, str]:
        return (fold_place(self.name), self.country_code)

    @property
    def display(self) -> str:
        return f"{self.name}, {self.country}" if self.country else self.name


@dataclass
class _Stop:
    city: _City
    members: list[tuple[int, dict, _City]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.members)

    @property
    def order(self) -> tuple[float, int]:
        hints = [p["day_hint"] for _, p, _ in self.members if p.get("day_hint")]
        return (min(hints) if hints else math.inf, min(i for i, _, _ in self.members))


def _resolve_city(city: str | None, country: str | None) -> _City | None:
    if not city:
        return None
    if fold_place(city) in country_names():
        return None  # "Portugal" is a country, not a town to stay in
    texts = [f"{city}, {country}", city] if country else [city]
    place = None
    for text in texts:
        place = resolve_place(text)
        if place:
            break
    if not place:
        return None
    lat, lng = place.lat, place.lng
    if lat is None or lng is None:
        lat, lng = lookup_coords(place.name) or (None, None)
    airports = list(place.airports)
    if not airports:
        codes = lookup_city_iata(place.name)
        airports = codes.split(",") if codes else []
    return _City(
        name=place.name,
        country_code=place.country_code,
        country=country_display_name(place.country_code),
        lat=lat,
        lng=lng,
        airports=airports[:3],
        population=place.population,
    )


def _km(a: _City, b: _City) -> float | None:
    if None in (a.lat, a.lng, b.lat, b.lng):
        return None
    return haversine_km(a.lat, a.lng, b.lat, b.lng)


def _group(resolved: list[tuple[int, dict, _City]]) -> list[_Stop]:
    """One stop per city; a town within a day trip of a bigger stop in the
    same country joins it ("Sintra" → Lisbon)."""
    by_city: dict[tuple[str, str], _Stop] = {}
    for idx, place, city in resolved:
        stop = by_city.setdefault(city.key, _Stop(city))
        stop.members.append((idx, place, city))
    anchors: list[_Stop] = []
    for stop in sorted(
        by_city.values(), key=lambda s: (-s.city.population, -s.count, s.order)
    ):
        host = next(
            (
                a
                for a in anchors
                if a.city.country_code == stop.city.country_code
                and (km := _km(a.city, stop.city)) is not None
                and km <= DAY_TRIP_KM
            ),
            None,
        )
        if host:
            host.members.extend(stop.members)
        else:
            anchors.append(stop)
    return sorted(anchors, key=lambda s: s.order)


def _split_nights(total: int, counts: list[int]) -> list[int]:
    """``total`` nights across stops by place count, at least one each."""
    n = len(counts)
    if n == 1:
        return [total]
    spare = total - n
    weights = sum(counts)
    raw = [spare * c / weights for c in counts]
    extra = [int(r) for r in raw]
    by_remainder = sorted(range(n), key=lambda i: (-(raw[i] - extra[i]), i))
    for i in by_remainder[: spare - sum(extra)]:
        extra[i] += 1
    return [1 + e for e in extra]


def _name_words(text: str) -> set[str]:
    return {
        w
        for w in fold_place(text).replace("-", " ").split()
        if len(w) > 2 and w not in STOP_WORDS
    }


async def _lookup_pois(
    targets: list[tuple[str, dict, _City]],
) -> dict[str, dict]:
    """Google Maps hits by place id, for at most MAX_SERPER_LOOKUPS places."""
    if not settings.serper_key or not targets:
        return {}
    client = SerperPlacesClient(settings.serper_key)
    cache = get_cache()
    semaphore = asyncio.Semaphore(SERPER_CONCURRENCY)

    async def one(pid: str, place: dict, city: _City) -> tuple[str, dict | None]:
        key = f"serper:poi:{fold_place(place['name'])}:{fold_place(city.display)}"
        if key in cache:
            return pid, cache[key] or None
        async with semaphore:
            hit = await client.lookup_place(f"{place['name']}, {city.display}")
        if hit:
            lat, lng = hit.get("latitude"), hit.get("longitude")
            far = (
                city.lat is not None
                and city.lng is not None
                and haversine_km(city.lat, city.lng, lat, lng) > SERPER_MAX_KM
            )
            words = _name_words(place["name"]) - _name_words(city.name)
            unrelated = bool(words) and not words & _name_words(
                f"{hit.get('title', '')} {hit.get('address', '')}"
            )
            if far or unrelated:
                hit = None
        cache[key] = hit or {}
        return pid, hit

    results = await asyncio.gather(
        *(one(pid, place, city) for pid, place, city in targets[:MAX_SERPER_LOOKUPS])
    )
    return {pid: hit for pid, hit in results if hit}


def _preview_place(pid: str, place: dict, **extra) -> dict:
    return {
        "id": pid,
        "name": place["name"],
        "kind": place.get("kind") or "sight",
        "city": place.get("city"),
        "country": place.get("country"),
        "destination": None,
        "lat": None,
        "lng": None,
        "approximate": True,
        "verified": False,
        "address": None,
        "rating": None,
        "note": place.get("note"),
        "quote": place.get("quote"),
        "day_hint": place.get("day_hint"),
        "confidence": place.get("confidence", 0.7),
        **extra,
    }


async def build_preview(extraction: dict, source: dict) -> dict:
    """The ImportPreview for a cleaned extraction (see schemas.link_import)."""
    places = extraction.get("places") or []
    mentioned = extraction.get("destinations_mentioned") or []
    lone_destination = mentioned[0] if len(mentioned) == 1 else None

    city_cache: dict[tuple, _City | None] = {}

    def resolve(city, country):
        key = (city, country)
        if key not in city_cache:
            city_cache[key] = _resolve_city(city, country)
        return city_cache[key]

    resolved: list[tuple[int, dict, _City]] = []
    unresolved: list[dict] = []
    for idx, place in enumerate(places):
        city = resolve(place.get("city"), place.get("country"))
        if city is None and not place.get("city") and lone_destination:
            city = resolve(lone_destination, None)
        if city is None:
            unresolved.append(_preview_place(f"p{idx + 1}", place))
        else:
            resolved.append((idx, place, city))

    stops = _group(resolved)
    kept = sorted(
        sorted(stops, key=lambda s: (-s.count, s.order))[:MAX_DESTINATIONS],
        key=lambda s: s.order,
    )
    dropped = [s for s in stops if s not in kept]

    visits = sum(
        1 for s in kept for _i, p, _c in s.members if p.get("kind") not in _NOT_A_VISIT
    )
    days = extraction.get("suggested_days") or min(
        MAX_DAYS, max(MIN_DAYS, math.ceil(visits / PLACES_PER_DAY))
    )
    days = max(days, len(kept))
    nights = _split_nights(days, [s.count for s in kept]) if kept else []

    members = [
        (f"p{idx + 1}", place, city, stop)
        for stop in kept
        for idx, place, city in stop.members
    ]
    targets = sorted(
        ((pid, place, stop.city) for pid, place, _c, stop in members),
        key=lambda t: -(t[1].get("confidence") or 0),
    )
    hits = await _lookup_pois(targets)

    out_places = []
    for pid, place, city, stop in members:
        hit = hits.get(pid)
        item = _preview_place(
            pid,
            place,
            city=city.name,
            country=city.country,
            destination=stop.city.display,
            lat=hit["latitude"] if hit else city.lat,
            lng=hit["longitude"] if hit else city.lng,
            approximate=not hit,
            verified=bool(hit),
            address=(hit or {}).get("address"),
            rating=(hit or {}).get("rating"),
        )
        out_places.append(item)
    stop_rank = {id(s): i for i, s in enumerate(kept)}
    order = {
        pid: (stop_rank[id(stop)], place.get("day_hint") or 99, int(pid[1:]))
        for pid, place, _c, stop in members
    }
    out_places.sort(key=lambda p: order[p["id"]])

    destinations = [
        {
            "name": stop.city.display,
            "city": stop.city.name,
            "country": stop.city.country,
            "airports": stop.city.airports,
            "lat": stop.city.lat,
            "lng": stop.city.lng,
            "place_count": stop.count,
            "nights": n,
        }
        for stop, n in zip(kept, nights)
    ]
    also = [{"name": s.city.display, "place_count": s.count} for s in dropped]

    warnings = []
    if also:
        names = ", ".join(f"{a['name']} ({a['place_count']})" for a in also)
        warnings.append(
            f"Also mentioned: {names}. We planned the {len(kept)} stops with the "
            "most places — plan another trip for the rest."
        )
    if unresolved:
        warnings.append(
            f"We couldn't place {len(unresolved)} "
            f"{'spot' if len(unresolved) == 1 else 'spots'} on the map — "
            "add a city to include them."
        )

    return {
        "source": source,
        "title": extraction.get("title") or source.get("title") or "Your imported trip",
        "summary": extraction.get("summary"),
        "destinations": destinations,
        "places": out_places,
        "unresolved": unresolved,
        "also_mentioned": also,
        "suggested_days": days,
        "season_hint": extraction.get("season_hint"),
        "interests": extraction.get("interests") or [],
        "warnings": warnings,
    }


async def resolve_one_place(place: dict) -> dict | None:
    """{place, destination} for one place whose town the traveller typed, or
    None when the town can't be resolved (a country, an unknown name)."""
    city = _resolve_city(place.get("city"), place.get("country"))
    if city is None:
        return None
    hits = await _lookup_pois([("p1", place, city)])
    hit = hits.get("p1")
    return {
        "place": _preview_place(
            place.get("id") or "p1",
            place,
            city=city.name,
            country=city.country,
            destination=city.display,
            lat=hit["latitude"] if hit else city.lat,
            lng=hit["longitude"] if hit else city.lng,
            approximate=not hit,
            verified=bool(hit),
            address=(hit or {}).get("address"),
            rating=(hit or {}).get("rating"),
        ),
        "destination": {
            "name": city.display,
            "city": city.name,
            "country": city.country,
            "airports": city.airports,
            "lat": city.lat,
            "lng": city.lng,
            "place_count": 1,
            "nights": 1,
        },
    }
