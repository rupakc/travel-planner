"""Trip geography: cities per day, countries and continents. No network."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.db.places_db import resolve_place
from app.schemas.request import allocate_city_days

_CONTINENTS_FILE = Path(__file__).resolve().parent.parent / "data" / "continents.json"


@lru_cache(maxsize=1)
def _continents() -> dict[str, str]:
    return json.loads(_CONTINENTS_FILE.read_text(encoding="utf-8"))


def continent_of(code: str) -> str | None:
    if not isinstance(code, str):
        return None
    return _continents().get(code.strip().upper())


def trip_cities(search_data: dict) -> list[str]:
    """Destination cities in order: ``destinations`` (2+), else ``destination``."""
    sd = search_data if isinstance(search_data, dict) else {}
    dests = sd.get("destinations")
    if isinstance(dests, list):
        cities = [d.strip() for d in dests if isinstance(d, str) and d.strip()]
        if len(cities) > 1:
            return cities
    dest = sd.get("destination")
    if isinstance(dest, str) and dest.strip():
        return [dest.strip()]
    return []


def city_for_day(
    search_data: dict, start: date, end: date | None, day_index: int
) -> str | None:
    """The city a 1-based trip day is spent in; past the last stay, the last city."""
    cities = trip_cities(search_data)
    if not cities:
        return None
    if len(cities) == 1:
        return cities[0]
    n = len(cities)
    total_days = (end - start).days if end else 2 * n
    total_days = max(total_days, n)
    nights = (search_data or {}).get("destination_nights")
    allocation = allocate_city_days(n, total_days, nights)
    offset = max(day_index, 1) - 1
    for city, days in zip(cities, allocation):
        if offset < days:
            return city
        offset -= days
    return cities[-1]


@lru_cache(maxsize=2048)
def country_of(place: str) -> str | None:
    if not isinstance(place, str) or not place.strip():
        return None
    try:
        found = resolve_place(place)
    except Exception:
        return None
    return found.country_code if found and found.country_code else None


def trip_countries(search_data: dict) -> list[str]:
    seen: list[str] = []
    for city in trip_cities(search_data):
        code = country_of(city)
        if code and code not in seen:
            seen.append(code)
    return seen
