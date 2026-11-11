"""Game hooks fired by trip events (stubs; the game task fills them in)."""

from datetime import date


def on_plan_saved(user_id: str, plan_id: int) -> dict | None:
    return None


def on_trip_ready(user_id: str, plan_id: int) -> dict | None:
    return None


def on_smart_planner(user_id: str, plan_id: int, score: int) -> dict | None:
    return None


def on_place_visited(user_id: str, plan_id: int, place_key: str) -> dict | None:
    return None


def on_trip_checkin(
    user_id: str, plan_id: int, day: date, new_countries: list[str]
) -> tuple[dict | None, dict | None]:
    """Return (game, streak)."""
    return None, None


def on_recap_complete(
    user_id: str, plan_id: int, new_countries: list[str]
) -> dict | None:
    return None


def on_traveller_type(user_id: str, traveller_type: str) -> dict | None:
    return None
