"""Trip phase and day arithmetic (contract "Phases"). Pure: no I/O.

The golden cases in ``tests/fixtures/journey/trip_phase_cases.json`` are shared
with the web, iOS and Android clients.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

READY_WINDOW_DAYS = 14
PHASES = ("dreaming", "planning", "ready", "on_the_road", "memories")


def _to_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def trip_dates(plan: dict) -> tuple[date | None, date | None]:
    """(start, end) of a plan: its columns, else ``search_data`` dates.

    An end before the start becomes the start; a missing end stays ``None``.
    """
    sd = plan.get("search_data")
    if not isinstance(sd, dict):
        sd = {}
    start = _to_date(plan.get("start_date")) or _to_date(sd.get("departure_date"))
    end = _to_date(plan.get("end_date")) or _to_date(sd.get("return_date"))
    if start is not None and end is not None and end < start:
        end = start
    return start, end


def effective_phase(
    start: date | None,
    end: date | None,
    override: str | None,
    today: date,
    prep_complete: bool,
    ready_window_days: int = READY_WINDOW_DAYS,
) -> str:
    if override:
        return override
    if start is None:
        return "dreaming"
    last = end if end is not None and end >= start else start
    if today > last:
        return "memories"
    if start <= today <= last:
        return "on_the_road"
    if prep_complete or (start - today).days <= ready_window_days:
        return "ready"
    return "planning"


def days_to_start(start: date | None, today: date) -> int | None:
    if start is None or today >= start:
        return None
    return (start - today).days


def day_index(start: date | None, end: date | None, today: date) -> int | None:
    if start is None:
        return None
    last = end if end is not None and end >= start else start
    if start <= today <= last:
        return (today - start).days + 1
    return None


def resolve_today(client_today: str | None, now: datetime | None = None) -> date:
    """The caller's local day: the client's ``today`` when within ±1 day of UTC."""
    utc_today = (now or datetime.now(UTC)).astimezone(UTC).date()
    if isinstance(client_today, str) and len(client_today) == 10:
        try:
            candidate = date.fromisoformat(client_today)
        except ValueError:
            return utc_today
        if abs((candidate - utc_today).days) <= 1:
            return candidate
    return utc_today


__all__ = [
    "READY_WINDOW_DAYS",
    "PHASES",
    "trip_dates",
    "effective_phase",
    "days_to_start",
    "day_index",
    "resolve_today",
]
