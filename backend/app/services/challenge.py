"""Weekly challenge ("Know before you go"). Pure selection over existing data:
the country of the caller's next upcoming trip when the bank has at least
three landmarks and dishes for it, else a featured pack of the ISO week.
No table of its own (its sessions are ``quiz_sessions`` rows of mode
``challenge``) and no network or model call."""

from datetime import UTC as _UTC
from datetime import date, datetime, timedelta

from ..db import plans_db, users_db
from ..game.quiz import engine as quiz_engine
from . import trip_geo
from .trip_phase import trip_dates

MIN_COUNTRY_ENTRIES = 3


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_start(d: date) -> date:
    """The Monday of ``d``'s ISO week (boards and challenges run from here)."""
    return d - timedelta(days=d.weekday())


def week_bounds_ms(d: date) -> tuple[int, int]:
    """[start, end) of ``d``'s ISO week in epoch ms, UTC."""
    s = datetime.combine(week_start(d), datetime.min.time())
    start = int(s.replace(tzinfo=_UTC).timestamp() * 1000)
    return start, start + 7 * 86_400_000


def featured_pack(d: date) -> str:
    """Deterministic by ISO week: packs rotate week by week."""
    y, w, _ = d.isocalendar()
    return quiz_engine.PACKS[(y * 53 + w) % len(quiz_engine.PACKS)]


def next_trip_country(username: str, today: date) -> str | None:
    """Country of the soonest trip starting today or later that the bank
    covers; trips whose country the bank lacks are skipped."""
    upcoming = []
    for plan in plans_db.get_user_plans(username):
        start, _ = trip_dates(plan)
        if start is not None and start >= today:
            upcoming.append((start, plan["id"], plan))
    for _, _, plan in sorted(upcoming, key=lambda t: t[:2]):
        for code in trip_geo.trip_countries(plan["search_data"]):
            if (
                code in quiz_engine.load_bank()["by_code"]
                and quiz_engine.country_entries(code) >= MIN_COUNTRY_ENTRIES
            ):
                return code
    return None


def current(user_id: str, today: date) -> dict:
    """``{id, kind, country?, pack?, week, title_key}`` for this user and week."""
    week = iso_week(today)
    user = users_db.get_user_by_id(user_id)
    code = next_trip_country(user["username"], today) if user else None
    if code:
        return {
            "id": f"{week}:{code}",
            "kind": "destination",
            "country": code,
            "week": week,
            "title_key": "play.challenge.destination",
        }
    pack = featured_pack(today)
    return {
        "id": f"{week}:{pack}",
        "kind": "featured",
        "pack": pack,
        "week": week,
        "title_key": f"play.challenge.featured.{pack}",
    }


def questions_for(ch: dict) -> list[dict]:
    seed = f"challenge:{ch['id']}"
    if ch["kind"] == "destination":
        return quiz_engine.build_country_questions(ch["country"], seed)
    return quiz_engine.build_questions(ch["pack"], seed)


def public(ch: dict, done: bool) -> dict:
    out = {
        "id": ch["id"],
        "kind": ch["kind"],
        "title_key": ch["title_key"],
        "done": done,
    }
    if ch["kind"] == "destination":
        out["country"] = ch["country"]
    return out
