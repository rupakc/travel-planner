"""Trips API: daily check-in."""

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...core.auth import get_current_user
from ...core.errors import ApiError
from ...core.trip_access import owned_trip
from ...db import trip_checkins_db, user_countries_db
from ...game import trip_hooks
from ...services import trip_geo
from ...services.trip_phase import day_index, trip_dates

router = APIRouter()


class CheckinRequest(BaseModel):
    day: str


@router.post("/trips/{plan_id}/checkin")
def checkin(
    plan_id: int, req: CheckinRequest, user: dict = Depends(get_current_user)
) -> dict:
    plan = owned_trip(plan_id, user)
    try:
        day = date.fromisoformat(req.day)
    except (TypeError, ValueError):
        raise ApiError(422, "checkin_day_invalid", "Invalid day") from None
    # The client's local day may differ from UTC by at most one day.
    if abs((day - datetime.now(UTC).date()).days) > 1:
        raise ApiError(422, "checkin_day_invalid", "Day is too far from today")
    start, end = trip_dates(plan)
    idx = day_index(start, end, day)
    if idx is None:
        raise ApiError(409, "checkin_out_of_trip", "That day is outside the trip")

    key = day.isoformat()
    base = {"day": key, "day_index": idx}
    existing = trip_checkins_db.get(plan_id, key)
    if existing:
        return _repeat(base, existing)
    city = trip_geo.city_for_day(plan.get("search_data") or {}, start, end, idx)
    code = trip_geo.country_of(city) if city else None
    if not trip_checkins_db.add(plan_id, key, city, code):
        # Lost a race with a parallel request for the same day.
        return _repeat(base, trip_checkins_db.get(plan_id, key) or {})
    new_countries: list[str] = []
    if code:
        new_countries = user_countries_db.add_countries(
            user["id"], [code], plan_id, source="checkin"
        )
    game, streak = trip_hooks.on_trip_checkin(user["id"], plan_id, day, new_countries)
    return {
        **base,
        "city": city,
        "country_code": code,
        "new_country": bool(new_countries),
        "streak": streak,
        "game": game,
    }


def _repeat(base: dict, row: dict) -> dict:
    return {
        **base,
        "city": row.get("city"),
        "country_code": row.get("country_code"),
        "new_country": False,
        "streak": None,
        "game": None,
    }


@router.get("/trips/{plan_id}/checkins")
def list_checkins(plan_id: int, user: dict = Depends(get_current_user)) -> dict:
    owned_trip(plan_id, user)
    return {"days": trip_checkins_db.list_days(plan_id), "streak": None}
