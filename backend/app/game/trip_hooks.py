"""Game hooks fired by trip events. Server-observed events only.

Every hook catches its own errors and returns an empty delta (never ``None``,
which reads as "game disabled"), so a game failure never breaks a trip route.
"""

import logging
from collections.abc import Callable
from datetime import date

from ..core.config import settings
from ..db import user_countries_db
from ..services.trip_geo import continent_of
from . import hooks

logger = logging.getLogger(__name__)


def merge_deltas(*deltas: dict | None) -> dict | None:
    """Sum awards, concatenate badges, keep the last xp, span level_up."""
    parts = [d for d in deltas if d]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    ups = [d["level_up"] for d in parts if d.get("level_up")]
    return {
        "xp": parts[-1]["xp"],
        "awards": [a for d in parts for a in d.get("awards", [])],
        "badges": [b for d in parts for b in d.get("badges", [])],
        "level_up": {"from": ups[0]["from"], "to": ups[-1]["to"]} if ups else None,
    }


def _award(user_id: str, rule: str, key: str, meta: dict | None = None) -> dict:
    from . import engine

    return engine.award(user_id, rule, key, meta=meta)


def _guard(user_id: str, label: str, fn: Callable[[], dict | None]) -> dict | None:
    if not settings.game_enabled:
        return None
    try:
        return fn()
    except Exception:
        logger.exception("game hook failed (%s)", label)
        return hooks._empty(user_id)


def _new_continents(user_id: str, new_countries: list[str]) -> list[str]:
    known = {c["country_code"] for c in user_countries_db.list_countries(user_id)}
    known -= set(new_countries)  # tolerate the hook running after the insert
    have = {continent_of(c) for c in known}
    out: list[str] = []
    for code in new_countries:
        cont = continent_of(code)
        if cont and cont not in have and cont not in out:
            out.append(cont)
    return out


def _countries(user_id: str, plan_id: int, new_countries: list[str]) -> dict | None:
    deltas = []
    conts = _new_continents(user_id, new_countries)
    for code in new_countries:
        deltas.append(
            _award(
                user_id,
                "country_visited",
                f"country_visited:{user_id}:{code}",
                {"plan_id": plan_id},
            )
        )
    for cont in conts:
        deltas.append(
            _award(
                user_id,
                "continent_visited",
                f"continent_visited:{user_id}:{cont}",
                {"plan_id": plan_id},
            )
        )
    return merge_deltas(*deltas)


def on_plan_saved(user_id: str, plan_id: int) -> dict | None:
    return _guard(
        user_id,
        "plan_saved",
        lambda: _award(user_id, "plan_saved", f"plan_saved:{plan_id}"),
    )


def on_trip_ready(user_id: str, plan_id: int) -> dict | None:
    return _guard(
        user_id,
        "trip_ready",
        lambda: _award(user_id, "trip_ready", f"trip_ready:{plan_id}"),
    )


def on_smart_planner(user_id: str, plan_id: int, score: int) -> dict | None:
    return _guard(
        user_id,
        "smart_planner",
        lambda: _award(
            user_id,
            "smart_planner",
            f"smart_planner:{plan_id}:{score}",
            {"score": score},
        ),
    )


def on_place_visited(user_id: str, plan_id: int, place_key: str) -> dict | None:
    return _guard(
        user_id,
        "place_visited",
        lambda: _award(
            user_id, "place_visited", f"place_visited:{plan_id}:{place_key}"
        ),
    )


def on_trip_checkin(
    user_id: str, plan_id: int, day: date, new_countries: list[str]
) -> tuple[dict | None, dict | None]:
    """Return (game, streak)."""
    if not settings.game_enabled:
        return None, None
    streak: dict | None = None

    def run() -> dict | None:
        nonlocal streak
        from . import engine

        d = _award(
            user_id,
            "trip_checkin",
            f"trip_checkin:{plan_id}:{day.isoformat()}",
            {"plan_id": plan_id},
        )
        streak = engine.touch_streak(user_id, "trip_checkin", day)
        return merge_deltas(d, _countries(user_id, plan_id, new_countries))

    return _guard(user_id, "trip_checkin", run), streak


def on_recap_complete(
    user_id: str, plan_id: int, new_countries: list[str]
) -> dict | None:
    return _guard(
        user_id,
        "recap_complete",
        lambda: merge_deltas(
            _award(user_id, "recap_complete", f"recap_complete:{plan_id}"),
            _countries(user_id, plan_id, new_countries),
        ),
    )


def on_traveller_type(user_id: str, traveller_type: str) -> dict | None:
    return _guard(
        user_id,
        "traveller_type",
        lambda: _award(user_id, "traveller_type", f"traveller_type:{user_id}"),
    )
