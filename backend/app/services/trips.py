"""The contract ``Trip`` object, list order and the pinned trip. Pure: no I/O
beyond the local place lookup behind ``trip_countries``."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from .trip_geo import trip_countries
from .trip_phase import day_index, days_to_start, effective_phase, trip_dates

PHASE_ORDER = ("on_the_road", "ready", "planning", "dreaming", "memories")
EMPTY_PREP = {"done": 0, "total": 0, "percent": 0, "complete": False}
RECAP_PIN_DAYS = 14
MAX_TRIPS = 200


def _iso_z(value) -> str | None:
    """SQLite ``datetime('now')`` ("YYYY-MM-DD HH:MM:SS", UTC) → ISO 8601 ``Z``."""
    if not isinstance(value, str) or not value:
        return None
    if value.endswith("Z"):
        return value
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _str(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value


def _destinations(sd: dict, destination: str | None) -> list[str]:
    dests = sd.get("destinations")
    if isinstance(dests, list):
        cities = [d.strip() for d in dests if isinstance(d, str) and d.strip()]
        if cities:
            return cities
    return [destination] if destination else []


def _has_itinerary(selections: dict) -> bool:
    itinerary = selections.get("itinerary")
    if isinstance(itinerary, dict) and itinerary.get("days"):
        return True
    if isinstance(itinerary, list) and itinerary:
        return True
    slots = selections.get("itinerary_slots")
    return isinstance(slots, list) and bool(slots)


def trip_view(plan: dict, *, today: date, prep: dict) -> dict:
    """The contract ``Trip`` for one plans row. Dates are normalised by
    ``trip_dates`` (a stored end before the start comes back as the start)."""
    sd = plan.get("search_data")
    sd = sd if isinstance(sd, dict) else {}
    selections = plan.get("selections")
    selections = selections if isinstance(selections, dict) else {}
    start, end = trip_dates(plan)
    override = plan.get("phase") or None
    phase = effective_phase(start, end, override, today, bool(prep.get("complete")))
    destination = _str(sd.get("destination"))
    return {
        "id": plan["id"],
        "title": plan.get("title") or plan.get("name"),
        "destination": destination,
        "destinations": _destinations(sd, destination),
        "origin": _str(sd.get("origin")),
        "start_date": start.isoformat() if start else None,
        "end_date": end.isoformat() if end else None,
        "nights": (end - start).days if start and end else None,
        "phase": phase,
        "phase_source": "manual" if override else "auto",
        "days_to_start": days_to_start(start, today),
        "day_index": day_index(start, end, today),
        "num_travelers": _number(sd.get("num_travelers")),
        "budget_usd": _number(sd.get("budget_usd")),
        "countries": trip_countries(sd),
        "prep": dict(EMPTY_PREP) if phase == "dreaming" else prep,
        "has_itinerary": _has_itinerary(selections),
        "recap_completed_at": plan.get("recap_completed_at"),
        "created_at": _iso_z(plan.get("created_at")),
        "updated_at": _iso_z(plan.get("updated_at")),
    }


def _ordinal(day: str | None) -> int:
    return date.fromisoformat(day).toordinal() if day else 0


def sort_trips(trips: list[dict]) -> list[dict]:
    """By phase (on the road, ready, planning, dreaming, memories), then start
    date (memories: newest first), then ``updated_at`` newest first."""
    by_updated = sorted(trips, key=lambda t: t.get("updated_at") or "", reverse=True)

    def key(t: dict) -> tuple:
        rank = PHASE_ORDER.index(t["phase"]) if t["phase"] in PHASE_ORDER else 99
        start = _ordinal(t.get("start_date"))
        missing = t.get("start_date") is None
        return rank, missing, -start if t["phase"] == "memories" else start

    return sorted(by_updated, key=key)


def pick_pinned(trips: list[dict], *, today: date | None = None) -> int | None:
    """The on-the-road trip with the earliest start, else the trip with the
    smallest ``days_to_start``, else the memories trip that ended in the last
    14 days with no completed recap (most recent end first), else None."""
    today = today or datetime.now(UTC).date()
    road = [t for t in trips if t.get("phase") == "on_the_road"]
    if road:
        return min(road, key=lambda t: _ordinal(t.get("start_date")))["id"]
    upcoming = [t for t in trips if t.get("days_to_start") is not None]
    if upcoming:
        return min(upcoming, key=lambda t: t["days_to_start"])["id"]
    oldest = today - timedelta(days=RECAP_PIN_DAYS)

    def last_day(t: dict) -> str | None:
        return t.get("end_date") or t.get("start_date")

    recent = [
        t
        for t in trips
        if t.get("phase") == "memories"
        and last_day(t)
        and not t.get("recap_completed_at")
        and oldest <= date.fromisoformat(last_day(t)) < today
    ]
    if recent:
        return max(recent, key=last_day)["id"]
    return None
