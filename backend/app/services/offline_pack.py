"""Offline pack: the data a traveller needs with no connection.

``build_pack`` is pure (no I/O beyond the static lookup tables), so it is
tested with plain dicts. It never copies personal search fields.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.agents.static_results import get_static_emergency_numbers
from app.db.places_db import country_display_name
from app.services.trip_geo import country_of, trip_cities
from app.services.trip_phase import trip_dates

SNAPSHOT_KEYS = ("emergency_card", "forex", "visa", "packing_list", "weather")
SELECTION_KEYS = (
    "itinerary",
    "itinerary_layout",
    "itinerary_edits",
    "itinerary_notes",
    "itinerary_slots",
    "hotel",
    "flight",
    "sim",
    "packing_list",
)


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _snapshot_emergency(snapshot: dict | None, cities: list[str]) -> list[dict] | None:
    card = (snapshot or {}).get("emergency_card")
    if not isinstance(card, dict) or card.get("error"):
        return None
    entries = card.get("cities")
    if not isinstance(entries, list):
        entries = [card] if card.get("emergency_numbers") else []
    out = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or not e.get("emergency_numbers"):
            continue
        out.append(
            {
                "city": e.get("city") or (cities[i] if i < len(cities) else None),
                "emergency_numbers": e["emergency_numbers"],
                "embassy": e.get("embassy"),
                "hospitals": e.get("hospitals") or [],
                "local_phrases": e.get("local_phrases") or [],
            }
        )
    return out or None


def _emergency(snapshot: dict | None, cities: list[str]) -> dict | None:
    ai = _snapshot_emergency(snapshot, cities)
    if ai:
        return {"source": "ai", "as_of": (snapshot or {}).get("as_of"), "cities": ai}
    static = []
    for city in cities:
        numbers = get_static_emergency_numbers(city)
        if numbers:
            static.append(
                {
                    "city": city,
                    "emergency_numbers": numbers,
                    "embassy": None,
                    "hospitals": [],
                    "local_phrases": [],
                }
            )
    if static:
        return {"source": "static", "as_of": None, "cities": static}
    return None


def _take_me_to(phrases: dict | None) -> dict | None:
    for item in (phrases or {}).get("items") or []:
        if isinstance(item, dict) and item.get("id") == "take_me_to":
            return {"text": item.get("text"), "romanized": item.get("romanized")}
    return None


def _address_card(selections: dict, city: str | None, phrases: dict | None):
    hotel = selections.get("hotel")
    if not isinstance(hotel, dict) or not hotel.get("name"):
        return None
    return {
        "hotel_name": hotel["name"],
        "area": hotel.get("location") or None,
        "city": city,
        "take_me_to": _take_me_to(phrases),
    }


def _currency(snapshot: dict | None) -> dict | None:
    from app.services.trip_money import usd_rate  # function-local: Task 9

    rate = usd_rate(snapshot)
    if not rate:
        return None
    return {
        "local": rate.get("local"),
        "home": "USD",
        "rate": rate.get("usd_to_local"),
        "as_of": rate.get("as_of"),
        "source": "snapshot",
    }


def build_pack(
    plan: dict, snapshot: dict | None, checkins: list[str], today: date
) -> dict:
    from app.services.phrases import phrases_for_country  # Task 1 stub / Task 12

    sd = plan.get("search_data") if isinstance(plan.get("search_data"), dict) else {}
    selections = (
        plan.get("selections") if isinstance(plan.get("selections"), dict) else {}
    )
    start, end = trip_dates(plan)
    cities = trip_cities(sd)

    destinations = []
    for city in cities:
        code = country_of(city)
        destinations.append(
            {
                "city": city,
                "country_code": code,
                "country_name": country_display_name(code) if code else None,
            }
        )

    phrases = None
    first_code = next(
        (d["country_code"] for d in destinations if d["country_code"]), None
    )
    if first_code:
        phrases = phrases_for_country(first_code)

    return {
        "version": 1,
        "trip_id": plan.get("id"),
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": plan.get("name"),
        "start_date": _iso(start),
        "end_date": _iso(end),
        "destinations": destinations,
        "emergency": _emergency(snapshot, cities),
        "phrases": phrases,
        "address_card": _address_card(
            selections, cities[0] if cities else None, phrases
        ),
        "currency": _currency(snapshot),
        "selections": {k: selections.get(k) for k in SELECTION_KEYS},
        "checkins": list(checkins),
    }
