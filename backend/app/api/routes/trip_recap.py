"""Trips API: recap and completion."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from ...core.auth import get_current_user
from ...core.errors import ApiError
from ...core.trip_access import owned_trip
from ...db import plans_db
from ...db.database import get_connection
from ...game import trip_hooks
from ...services.trip_geo import trip_countries
from ...services.trip_phase import resolve_today, trip_dates

router = APIRouter()


@router.get("/trips/{plan_id}/recap")
def get_recap(
    plan_id: int, today: str | None = None, user: dict = Depends(get_current_user)
) -> dict:
    from ...db import trip_checkins_db, trip_journal_db, user_countries_db
    from ...services.trip_money import spend_summary
    from ...services.trip_recap import build_recap

    plan = owned_trip(plan_id, user)
    owned = {
        c["country_code"]
        for c in user_countries_db.list_countries(user["id"])
        if c.get("first_plan_id") != plan_id
    }
    return build_recap(
        plan,
        places=trip_journal_db.list_places(plan_id),
        journal_count=len(trip_journal_db.list_entries(plan_id)),
        checkin_days=len(trip_checkins_db.list_days(plan_id)),
        spend=spend_summary(plan),
        user_country_codes=owned,
        today=resolve_today(today),
    )


@router.post("/trips/{plan_id}/recap/complete")
def complete_recap(
    plan_id: int, today: str | None = None, user: dict = Depends(get_current_user)
) -> dict:
    from ...db import user_countries_db

    plan = owned_trip(plan_id, user)
    _, end = trip_dates(plan)
    if end is None or resolve_today(today) <= end:
        raise ApiError(409, "recap_not_ready", "The trip has not ended yet")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        won = conn.execute(
            "UPDATE plans SET recap_completed_at = ? "
            "WHERE id = ? AND recap_completed_at IS NULL",
            (now, plan_id),
        ).rowcount
    if not won:
        first = (plans_db.get_plan(plan_id) or {}).get("recap_completed_at") or now
        return {"completed_at": first, "new_countries": [], "game": None}
    new = user_countries_db.add_countries(
        user["id"], trip_countries(plan["search_data"]), plan_id, source="recap"
    )
    game = trip_hooks.on_recap_complete(user["id"], plan_id, new)
    return {"completed_at": now, "new_countries": new, "game": game}
