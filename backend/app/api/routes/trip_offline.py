"""Trips API: trip snapshot and offline pack."""

import json
import logging

from fastapi import APIRouter, Depends, Request, Response

from ...core.auth import get_current_user
from ...core.config import settings
from ...core.errors import ApiError
from ...core.trip_access import owned_trip
from ...db import trip_prep_db, trip_snapshot_db
from ...services import trip_prep
from ...services.offline_pack import SNAPSHOT_KEYS, build_pack
from ...services.trip_phase import resolve_today

logger = logging.getLogger(__name__)

router = APIRouter()


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
    if len(json.dumps(data).encode("utf-8")) > settings.trip_snapshot_max_bytes:
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

    if not settings.offline_pack_enabled:
        # The kill switch (features.offline_pack false) also holds server-side.
        raise ApiError(404, "offline_pack_disabled", "Offline packs are turned off")
    plan = owned_trip(trip_id, user)
    day = resolve_today(today)
    pack = build_pack(
        plan,
        trip_snapshot_db.get_snapshot(trip_id),
        list(list_days(trip_id)),
        day,
    )
    try:
        trip_prep_db.set_done(trip_id, "offline_pack", True)
        trip_prep.maybe_award_trip_ready(plan, user["id"], day)
    except Exception:
        logger.exception("offline-pack prep tick failed for trip %s", trip_id)
    response.headers["Cache-Control"] = "no-store"
    return pack
