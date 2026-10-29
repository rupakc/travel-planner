"""Per-destination comparison summary.

``summarize_destination`` is a pure function: it condenses raw agent outputs
(flights, hotels, weather, visa) plus the static confidence score into the
small, NaN-free dict the Compare view renders.  A piece passed as ``None``
is treated as failed and listed in ``missing``.
"""

import math
import statistics

from ..agents.static_results import get_destination_daily_cost
from ..schemas.request import TravelSearchRequest

DEFAULT_NIGHTS = 7


def _num(value) -> float | None:
    """Coerce to a finite float, or None for junk (bool, NaN, inf, non-numeric)."""
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _positive(value) -> float | None:
    f = _num(value)
    return f if f is not None and f > 0 else None


def _round(value: float | None, digits: int = 0):
    if value is None:
        return None
    r = round(value, digits)
    return int(r) if digits == 0 else r


def _obj(value) -> dict:
    return value if isinstance(value, dict) else {}


def _dicts(value) -> list[dict]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _leg_sum(fare: dict, key: str) -> float | None:
    """Sum a numeric field over outbound + return legs; None if neither has it."""
    values = [
        v
        for leg in ("outbound", "return")
        if isinstance(fare.get(leg), dict)
        and (v := _num(fare[leg].get(key))) is not None
        and v >= 0
    ]
    return sum(values) if values else None


def _summarize_flight(flights: dict | None) -> dict | None:
    fares = []
    for fare in _dicts(_obj(flights).get("results")):
        price = _positive(fare.get("price_usd"))
        if price is not None:
            fares.append((price, fare))
    if not fares:
        return None
    real = [f for f in fares if f[1].get("source") != "estimate"]
    price, fare = min(real or fares, key=lambda f: f[0])
    outbound = fare.get("outbound") if isinstance(fare.get("outbound"), dict) else {}
    stops = _leg_sum(fare, "stops")
    duration = _leg_sum(fare, "duration_minutes")
    airline = outbound.get("airline")
    return {
        "price_usd": _round(price, 2),
        "stops": _round(stops),
        "duration_minutes": _round(duration),
        "airline": airline if isinstance(airline, str) and airline else None,
        "source": fare.get("source") if isinstance(fare.get("source"), str) else None,
    }


def _summarize_hotel(hotels: dict | None) -> dict | None:
    priced = []
    for h in _dicts(_obj(hotels).get("results")):
        price = _positive(h.get("price_per_night_usd"))
        if price is not None:
            priced.append((price, h))
    if not priced:
        return None
    mid = [
        p
        for p, h in priced
        if (stars := _num(h.get("star_rating"))) is not None and 3 <= stars <= 4
    ]
    good = [
        p
        for p, h in priced
        if (score := _num(h.get("review_score"))) is not None and score >= 7
    ]
    typical = statistics.median(mid or [p for p, _ in priced])
    return {
        "typical_nightly_usd": _round(typical, 2),
        "cheapest_good_nightly_usd": _round(min(good), 2) if good else None,
        "count": len(priced),
    }


def _avg(values: list[float]) -> float | None:
    return _round(sum(values) / len(values), 1) if values else None


def _summarize_weather(weather: dict | None) -> dict | None:
    days = _dicts(_obj(weather).get("days"))
    if not days:
        return None
    highs = [v for d in days if (v := _num(d.get("temp_high_c"))) is not None]
    lows = [v for d in days if (v := _num(d.get("temp_low_c"))) is not None]
    source = _obj(weather).get("source")
    return {
        "avg_high_c": _avg(highs),
        "avg_low_c": _avg(lows),
        "poor_days": sum(1 for d in days if d.get("is_poor") is True),
        "total_days": len(days),
        "source": source if isinstance(source, str) else None,
    }


def _summarize_visa(visa: dict | None, verified: bool) -> dict | None:
    if not isinstance(visa, dict):
        return None
    req = visa.get("requirement")
    if not isinstance(req, dict):
        return None
    visa_type = req.get("visa_type")
    if not isinstance(visa_type, str) or not visa_type:
        return None
    fee = _num(req.get("fee_usd"))
    stay = _num(req.get("max_stay_days"))
    processing = req.get("processing_time")
    return {
        "visa_type": visa_type,
        "max_stay_days": _round(stay) if stay is not None and stay > 0 else None,
        "fee_usd": _round(fee, 2) if fee is not None and fee >= 0 else None,
        "processing_time": processing if isinstance(processing, str) else None,
        "verified": bool(verified),
    }


def _summarize_ease(confidence: dict | None) -> dict | None:
    if not isinstance(confidence, dict):
        return None
    subs = confidence.get("sub_scores")
    subs = subs if isinstance(subs, dict) else {}

    def sub(key: str):
        entry = subs.get(key)
        return _round(_num(entry.get("score"))) if isinstance(entry, dict) else None

    grade = confidence.get("grade")
    return {
        "total": _round(_num(confidence.get("total"))),
        "grade": grade if isinstance(grade, str) else None,
        "safety": sub("safety"),
        "english": sub("english_friendliness"),
        "infrastructure": sub("tourist_infrastructure"),
        "visa_ease": sub("visa_ease"),
    }


def _label(request: TravelSearchRequest, flights: dict | None, hotels: dict | None):
    candidates = [_obj(hotels).get("destination")]
    for fare in _dicts(_obj(flights).get("results")):
        if isinstance(fare.get("outbound"), dict):
            candidates.append(fare["outbound"].get("destination"))
    for c in candidates:
        if isinstance(c, str) and "," in c:
            first = c.split(",")[0].strip()
            if first:
                return first
    return request.destination


def _estimate(request, flight, hotel, daily_cost) -> dict:
    nights = (
        (request.return_date - request.departure_date).days
        if request.return_date
        else DEFAULT_NIGHTS
    )
    nights = max(nights, 0)
    days = max(nights, 1)
    flight_usd = flight["price_usd"] if flight else None
    nightly = hotel["typical_nightly_usd"] if hotel else None
    n = max(request.num_travelers, 1)
    # A nightly price is per room; assume one room per two travellers.
    stay_usd = (
        _round(nightly * nights * math.ceil(n / 2) / n, 2)
        if nightly is not None
        else None
    )
    daily_usd = _round(daily_cost * days, 2) if daily_cost is not None else None
    parts = [p for p in (flight_usd, stay_usd, daily_usd) if p is not None]
    partial = len(parts) < 3
    total = _round(sum(parts), 2) if parts else None

    budget = _positive(request.budget_usd)
    status = None
    if total is not None and budget is not None:
        # Budget is for the whole party; the estimate is per traveller.
        party_total = total * max(request.num_travelers, 1)
        if party_total > budget:
            status = "over"
        elif not partial:
            status = "under"  # a partial total can't prove we're under budget
    return {
        "total_usd": total,
        "flight_usd": flight_usd,
        "stay_usd": stay_usd,
        "daily_usd": daily_usd,
        "nights": nights,
        "partial": partial,
        "budget_status": status,
    }


def summarize_destination(
    request: TravelSearchRequest,
    flights: dict | None,
    hotels: dict | None,
    weather: dict | None,
    visa: dict | None,
    confidence: dict | None,
    visa_verified: bool = False,
) -> dict:
    """Condense raw agent output into the comparison summary.

    A ``None`` flights/hotels/weather/visa means that piece failed and is
    reported in ``missing``; empty or junk data simply yields a ``null`` entry.
    """
    flight = _summarize_flight(flights)
    hotel = _summarize_hotel(hotels)
    daily_cost = get_destination_daily_cost(request)
    pieces = {"flights": flights, "hotels": hotels, "weather": weather, "visa": visa}
    return {
        "destination": request.destination,
        "label": _label(request, flights, hotels),
        "flight": flight,
        "hotel": hotel,
        "weather": _summarize_weather(weather),
        "visa": _summarize_visa(visa, visa_verified),
        "ease": _summarize_ease(confidence),
        "daily_cost_usd": daily_cost,
        "estimate": _estimate(request, flight, hotel, daily_cost),
        "missing": [name for name, data in pieces.items() if data is None],
    }
