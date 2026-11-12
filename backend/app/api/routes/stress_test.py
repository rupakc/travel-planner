import logging
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import Field

from ...agents.stress_test_agent import StressTestAgent
from ...core.auth import get_optional_user
from ...core.config import settings
from ...db import plans_db, trip_prep_db
from ...game import trip_hooks
from ...schemas.request import TravelSearchRequest
from ...services import trip_prep

logger = logging.getLogger(__name__)

router = APIRouter()


class StressTestRequest(TravelSearchRequest):
    """Stress-test the assembled plan: itinerary plus optional context."""

    itinerary: dict = Field(..., description="Itinerary with days/slots to audit")
    flights: dict | None = Field(None, description="Flight results for timing checks")
    visa: dict | None = Field(None, description="Visa requirement context")
    weather: dict | None = Field(None, description="Weather forecast context")
    plan_id: int | None = Field(None, description="Trip whose prep to update")


def _score(result) -> int | None:
    if not isinstance(result, dict):
        return None
    for key in ("overall_score", "score"):
        v = result.get(key)
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100:
            return v
    return None


def _record_progress(plan_id: int, user: dict, result) -> None:
    """Store the score, tick the prep item and award; never raises."""
    try:
        plan = plans_db.get_plan(plan_id)
        owner = plan.get("username") if plan else None
        if not owner or owner != user.get("username"):
            return
        score = _score(result)
        if score is None:
            return
        previous = (trip_prep_db.get_meta(plan_id, "stress_test") or {}).get("score")
        trip_prep_db.set_meta(plan_id, "stress_test", {"score": score})
        trip_prep_db.set_done(plan_id, "stress_test", True)
        if not isinstance(previous, int) or score > previous:
            trip_hooks.on_smart_planner(user["id"], plan_id, score)
        trip_prep.maybe_award_trip_ready(plan, user["id"], date.today())
    except Exception:
        logger.exception("stress-test progress failed for trip %s", plan_id)


@router.post("/stress-test")
async def stress_test(
    request: StressTestRequest, user: dict | None = Depends(get_optional_user)
):
    agent = StressTestAgent(settings.agents_dir)
    result = await agent.run(
        request,
        itinerary=request.itinerary,
        flights=request.flights,
        visa=request.visa,
        weather=request.weather,
    )
    if request.plan_id is not None and user:
        _record_progress(request.plan_id, user, result)
    return result
