"""
Build the best-value travel package from raw search results.
Picks cheapest qualifying flight, best-rated mid-range hotel,
top affordable activities, and cheapest SIM plan.
"""

from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _pick_flight(flights: list[dict]) -> dict | None:
    """Cheapest flight with at most 1 stop."""
    eligible = [
        f
        for f in flights
        if isinstance(f, dict) and _safe_float(f.get("stops"), 99) <= 1
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda f: _safe_float(f.get("price_usd"), float("inf")))


def _pick_luxury_flight(flights: list[dict]) -> dict | None:
    """Most expensive flight (for savings baseline)."""
    if not flights:
        return None
    return max(flights, key=lambda f: _safe_float(f.get("price_usd"), 0))


def _pick_hotel(hotels: list[dict]) -> dict | None:
    """Best-rated mid-range hotel."""
    mid = [
        h
        for h in hotels
        if isinstance(h, dict)
        and str(h.get("budget_tier", "")).lower()
        in {"mid-range", "mid_range", "midrange"}
    ]
    if not mid:
        return None
    return max(mid, key=lambda h: _safe_float(h.get("rating") or h.get("stars"), 0))


def _pick_luxury_hotel(hotels: list[dict]) -> dict | None:
    """Most expensive hotel (for savings baseline)."""
    if not hotels:
        return None
    return max(hotels, key=lambda h: _safe_float(h.get("price_per_night_usd"), 0))


def _pick_activities(activities: list[dict], max_count: int = 3) -> list[dict]:
    """Top-rated free/cheap activities (price < $80)."""
    cheap = [
        a
        for a in activities
        if isinstance(a, dict) and _safe_float(a.get("price_usd"), 0) < 80
    ]
    cheap.sort(
        key=lambda a: _safe_float(a.get("relevance_score") or a.get("rating"), 0),
        reverse=True,
    )
    return cheap[:max_count]


def _pick_sim(sim_plans: list[dict]) -> dict | None:
    """Cheapest SIM/eSIM plan."""
    valid = [s for s in sim_plans if isinstance(s, dict)]
    if not valid:
        return None
    return min(valid, key=lambda s: _safe_float(s.get("price_usd"), float("inf")))


def build_smart_package(
    sections: dict,
    budget_usd: float,
    num_travelers: int,
    nights: int,
) -> dict:
    """
    Build the best-value package from aggregated search sections.

    Parameters
    ----------
    sections : dict
        Expects keys: 'flights', 'hotels', 'activities', 'sim'.
        Each value is a list of dicts (the agent's results).
    budget_usd : float
        Total trip budget in USD.
    num_travelers : int
        Number of travellers (used for cost display only).
    nights : int
        Number of nights at the destination.

    Returns
    -------
    dict with keys:
        flight, hotel, activities, sim,
        total_cost_usd, savings_vs_expensive.
    Returns {} if no flights or hotels are available.
    """
    flights: list[dict] = sections.get("flights") or []
    hotels: list[dict] = sections.get("hotels") or []
    activities: list[dict] = sections.get("activities") or []
    sim_plans: list[dict] = sections.get("sim") or []

    chosen_flight = _pick_flight(flights)
    chosen_hotel = _pick_hotel(hotels)

    if not chosen_flight or not chosen_hotel:
        return {}

    chosen_activities = _pick_activities(activities)
    chosen_sim = _pick_sim(sim_plans)

    flight_cost = _safe_float(chosen_flight.get("price_usd"))
    hotel_cost = _safe_float(chosen_hotel.get("price_per_night_usd")) * nights
    activity_cost = sum(_safe_float(a.get("price_usd")) for a in chosen_activities)
    sim_cost = _safe_float(chosen_sim.get("price_usd") if chosen_sim else 0)

    total_cost = flight_cost + hotel_cost + activity_cost + sim_cost

    # Savings vs most expensive options
    luxury_flight = _pick_luxury_flight(flights)
    luxury_hotel = _pick_luxury_hotel(hotels)
    expensive_total = (
        _safe_float(luxury_flight.get("price_usd") if luxury_flight else 0)
        + _safe_float(luxury_hotel.get("price_per_night_usd") if luxury_hotel else 0)
        * nights
    )
    savings = max(0.0, expensive_total - (flight_cost + hotel_cost))

    return {
        "flight": chosen_flight,
        "hotel": chosen_hotel,
        "activities": chosen_activities,
        "sim": chosen_sim,
        "total_cost_usd": round(total_cost, 2),
        "savings_vs_expensive": round(savings, 2),
    }
