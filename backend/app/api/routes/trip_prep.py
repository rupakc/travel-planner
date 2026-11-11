"""Trips API: prep checklist."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ...core.auth import get_current_user
from ...core.errors import ApiError
from ...core.trip_access import owned_trip
from ...db import trip_prep_db
from ...game import trip_hooks
from ...services import trip_prep
from ...services.trip_phase import resolve_today

router = APIRouter()


class PrepDone(BaseModel):
    done: bool


@router.get("/trips/{plan_id}/prep")
def get_prep(
    plan_id: int,
    today: str | None = Query(None),
    user: dict = Depends(get_current_user),
):
    plan = owned_trip(plan_id, user)
    return trip_prep.prep_payload(plan, resolve_today(today))


@router.put("/trips/{plan_id}/prep/{item_id}")
def put_prep(
    plan_id: int,
    item_id: str,
    body: PrepDone,
    today: str | None = Query(None),
    user: dict = Depends(get_current_user),
):
    plan = owned_trip(plan_id, user)
    if item_id not in trip_prep.ITEM_IDS:
        raise ApiError(404, "prep_item_unknown", "Unknown prep item")
    if item_id in trip_prep.AUTO_ITEMS:
        raise ApiError(409, "prep_item_auto", "This item is ticked automatically")
    day = resolve_today(today)
    current = trip_prep.prep_payload(plan, day)
    item = next(i for i in current["items"] if i["id"] == item_id)
    if item["status"] == "na":
        raise ApiError(409, "prep_item_na", "This item does not apply to the trip")

    trip_prep_db.set_done(plan_id, item_id, body.done)
    payload = trip_prep.prep_payload(plan, day)
    game = None
    if payload["complete"] and not trip_prep_db.get_meta(
        plan_id, trip_prep.READY_AWARD_KEY
    ):
        trip_prep_db.set_meta(plan_id, trip_prep.READY_AWARD_KEY, {"awarded": True})
        game = trip_hooks.on_trip_ready(user["id"], plan_id)
    return {
        **payload,
        "item": next(i for i in payload["items"] if i["id"] == item_id),
        "game": game,
    }
