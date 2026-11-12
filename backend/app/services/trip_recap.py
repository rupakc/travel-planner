"""Trip recap: pure summary of a finished trip (contract "Recap")."""

from __future__ import annotations

import math
from datetime import date

from ..db.places_db import country_display_name
from .trip_geo import continent_of, trip_countries
from .trip_phase import trip_dates

ROUTE_MAX_POINTS = 500
_EARTH_RADIUS_KM = 6371.0088


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def _route(places: list[dict]) -> list[list[float]]:
    pts = []
    for p in places:
        if not p.get("visited"):
            continue
        lat, lng = _num(p.get("lat")), _num(p.get("lng"))
        if lat is None or lng is None:
            continue
        pts.append((p.get("day") or "", p.get("visited_at") or "", [lat, lng]))
    pts.sort(key=lambda t: (t[0], t[1]))
    return [p[2] for p in pts][:ROUTE_MAX_POINTS]


def _planned_days(selections: dict) -> int:
    slots = selections.get("itinerary_slots") if isinstance(selections, dict) else None
    if not isinstance(slots, list):
        return 0
    return len({s.get("day") for s in slots if isinstance(s, dict) and s.get("day")})


def build_recap(
    plan: dict,
    *,
    places: list[dict],
    journal_count: int,
    checkin_days: int,
    spend: dict,
    user_country_codes: set[str],
    today: date,
) -> dict:
    """``user_country_codes`` are the traveller's countries not first added by
    this plan; a trip country outside it is ``new``."""
    sd = plan.get("search_data") if isinstance(plan.get("search_data"), dict) else {}
    start, end = trip_dates(plan)
    last = end or start
    days = ((last - start).days + 1) if start and last else 0
    route = _route(places)
    distance = None
    if len(route) >= 2:
        distance = round(
            sum(haversine_km(tuple(a), tuple(b)) for a, b in zip(route, route[1:])), 1
        )
    stars = [
        p["stars"]
        for p in places
        if isinstance(p.get("stars"), int) and not isinstance(p["stars"], bool)
    ]
    codes = trip_countries(sd)
    continents: list[str] = []
    for c in codes:
        cont = continent_of(c)
        if cont and cont not in continents:
            continents.append(cont)
    completed_at = plan.get("recap_completed_at")
    return {
        "trip_id": plan["id"],
        "title": plan.get("title") or plan.get("name"),
        "start_date": start.isoformat() if start else None,
        "end_date": end.isoformat() if end else None,
        "days": days,
        "nights": max(days - 1, 0),
        "planned_days": _planned_days(plan.get("selections")),
        "places": places,
        "visited_count": sum(1 for p in places if p.get("visited")),
        "rated_count": len(stars),
        "avg_stars": round(sum(stars) / len(stars), 1) if stars else None,
        "route": route,
        "distance_km": distance,
        "countries": [
            {
                "code": c,
                "name": country_display_name(c),
                "new": c not in user_country_codes,
            }
            for c in codes
        ],
        "continents": continents,
        "spend": {
            "budget_usd": sd.get("budget_usd"),
            "plan_cost_usd": None,
            "spent_usd": spend.get("spent_usd"),
            "by_category_usd": spend.get("by_category_usd", {}),
            "unconverted": spend.get("unconverted", []),
        },
        "journal_count": journal_count,
        "checkin_days": checkin_days,
        "completed_at": completed_at,
        "can_complete": bool(end and today > end and not completed_at),
    }
