"""Trips API: a trip is a saved plan (contract "Trips")."""

from datetime import date

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...core.errors import ApiError
from ...core.trip_access import owned_trip
from ...db import plans_db, trips_db
from ...db import user_settings_db as sdb
from ...db.places_db import country_display_name
from ...db.user_countries_db import list_countries
from ...services import trip_prep
from ...services import trips as trips_service
from ...services.trip_geo import continent_of
from ...services.trip_phase import PHASES, resolve_today, trip_dates

router = APIRouter()

TITLE_MAX = 80
MAX_SPAN_DAYS = 365
YEAR_MIN, YEAR_MAX = 2000, 2100


class CreateTripRequest(BaseModel):
    title: str
    destination: str | None = Field(None, max_length=120)
    start_date: str | None = None
    end_date: str | None = None


class PatchTripRequest(BaseModel):
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    phase: str | None = None


def _title(raw) -> str:
    title = raw.strip() if isinstance(raw, str) else ""
    if not 1 <= len(title) <= TITLE_MAX:
        raise ApiError(422, "trip_title_invalid", "Trip title is not valid.")
    return title


def _dates_invalid() -> ApiError:
    return ApiError(422, "trip_dates_invalid", "Trip dates are not valid.")


def _day(raw: str | None) -> date | None:
    if raw is None:
        return None
    if len(raw) != 10:
        raise _dates_invalid()
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        raise _dates_invalid() from None
    if not YEAR_MIN <= day.year <= YEAR_MAX:
        raise _dates_invalid()
    return day


def _check_span(start: date | None, end: date | None) -> None:
    if start and end and (end < start or (end - start).days > MAX_SPAN_DAYS):
        raise _dates_invalid()


def _view(plan: dict, today: date) -> dict:
    prep = trip_prep.prep_summary(plan, today)
    return trips_service.trip_view(plan, today=today, prep=prep)


@router.get("/trips")
def list_trips(today: str | None = None, user: dict = Depends(get_current_user)):
    day = resolve_today(today)
    views = [_view(p, day) for p in plans_db.get_user_plans(user["username"])]
    trips = trips_service.sort_trips(views)[: trips_service.MAX_TRIPS]
    return {
        "trips": trips,
        "pinned_id": trips_service.pick_pinned(trips, today=day),
        "today": day.isoformat(),
    }


@router.post("/trips", status_code=201)
def create_trip(
    body: CreateTripRequest,
    today: str | None = None,
    user: dict = Depends(get_current_user),
):
    title = _title(body.title)
    start, end = _day(body.start_date), _day(body.end_date)
    _check_span(start, end)
    destination = body.destination.strip() if body.destination else None
    plan_id = trips_db.create_trip(
        user["username"],
        title,
        destination or None,
        start.isoformat() if start else None,
        end.isoformat() if end else None,
    )
    return _view(plans_db.get_plan(plan_id), resolve_today(today))


@router.get("/trips/stats")
def trip_stats(today: str | None = None, user: dict = Depends(get_current_user)):
    day = resolve_today(today)
    countries = [
        {
            "code": row["country_code"],
            "name": country_display_name(row["country_code"]),
            "first_trip_id": row["first_plan_id"],
            "visited_at": row["visited_at"],
            "source": row["source"],
        }
        for row in list_countries(user["id"])
    ]
    continents = sorted(
        {c for c in (continent_of(row["code"]) for row in countries) if c}
    )
    by_phase = dict.fromkeys(PHASES, 0)
    for plan in plans_db.get_user_plans(user["username"]):
        by_phase[_view(plan, day)["phase"]] += 1
    goal = sdb.get_settings(user["id"]).get("bucket_list_goal")
    return {
        "countries": countries,
        "continents": continents,
        "bucket_goal": goal if isinstance(goal, int) else None,
        "trips_by_phase": by_phase,
    }


@router.get("/trips/{trip_id}")
def get_trip(
    trip_id: int, today: str | None = None, user: dict = Depends(get_current_user)
):
    return _view(owned_trip(trip_id, user), resolve_today(today))


@router.patch("/trips/{trip_id}")
def patch_trip(
    trip_id: int,
    body: PatchTripRequest,
    today: str | None = None,
    user: dict = Depends(get_current_user),
):
    plan = owned_trip(trip_id, user)
    sent = body.model_fields_set
    fields: dict = {}
    if "title" in sent:
        fields["title"] = _title(body.title)
    if "phase" in sent:
        if body.phase is not None and body.phase not in PHASES:
            raise ApiError(422, "trip_phase_invalid", "Trip phase is not valid.")
        fields["phase"] = body.phase
    if sent & {"start_date", "end_date"}:
        start, end = trip_dates(plan)
        if "start_date" in sent:
            start = _day(body.start_date)
            fields["start_date"] = start.isoformat() if start else None
        if "end_date" in sent:
            end = _day(body.end_date)
            fields["end_date"] = end.isoformat() if end else None
        _check_span(start, end)
    if fields:
        trips_db.set_trip_fields(trip_id, **fields)
    return _view(plans_db.get_plan(trip_id), resolve_today(today))


@router.delete("/trips/{trip_id}", status_code=204)
def delete_trip(trip_id: int, user: dict = Depends(get_current_user)):
    owned_trip(trip_id, user)
    plans_db.delete_plan(trip_id, user["username"])
    return Response(status_code=204)
