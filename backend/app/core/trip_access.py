"""Trip ownership check shared by every trips route."""

from ..db import plans_db
from .errors import ApiError


def owned_trip(plan_id: int, user: dict) -> dict:
    plan = plans_db.get_plan(plan_id)
    owner = plan.get("username") if plan else None
    if not owner or owner != user.get("username"):
        raise ApiError(404, "trip_not_found", "Trip not found")
    return plan
