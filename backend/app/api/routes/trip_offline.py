"""Trips API: trip snapshot and offline pack."""

import json

from fastapi import APIRouter, Depends, Request, Response

from ...core.auth import get_current_user
from ...core.errors import ApiError
from ...core.trip_access import owned_trip
from ...db import trip_snapshot_db
from ...services.offline_pack import SNAPSHOT_KEYS, build_pack
from ...services.trip_phase import resolve_today

router = APIRouter()

MAX_SNAPSHOT_BYTES = 262144


@router.put("/trips/{trip_id}/snapshot", status_code=204)
async def put_snapshot(
    trip_id: int, request: Request, user: dict = Depends(get_current_user)
):
    owned_trip(trip_id, user)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise ApiError(422, "snapshot_invalid", "Snapshot must be a JSON object")
    data = {k: body[k] for k in SNAPSHOT_KEYS if k in body}
    if any(v is not None and not isinstance(v, dict) for v in data.values()):
        raise ApiError(422, "snapshot_invalid", "Snapshot values must be objects")
    if len(json.dumps(data).encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ApiError(413, "snapshot_too_large", "Snapshot is too large")
    trip_snapshot_db.put_snapshot(trip_id, data)
    return Response(status_code=204)


@router.get("/trips/{trip_id}/offline-pack")
def get_offline_pack(
    trip_id: int,
    response: Response,
    today: str | None = None,
    user: dict = Depends(get_current_user),
):
    from ...db.trip_checkins_db import list_days  # function-local: Task 14

    plan = owned_trip(trip_id, user)
    pack = build_pack(
        plan,
        trip_snapshot_db.get_snapshot(trip_id),
        list(list_days(trip_id)),
        resolve_today(today),
    )
    response.headers["Cache-Control"] = "no-store"
    return pack
