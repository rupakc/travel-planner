from fastapi import APIRouter
from pydantic import Field

from ...agents.stress_test_agent import StressTestAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest

router = APIRouter()


class StressTestRequest(TravelSearchRequest):
    """Stress-test the assembled plan: itinerary plus optional context."""

    itinerary: dict = Field(..., description="Itinerary with days/slots to audit")
    flights: dict | None = Field(None, description="Flight results for timing checks")
    visa: dict | None = Field(None, description="Visa requirement context")
    weather: dict | None = Field(None, description="Weather forecast context")


@router.post("/stress-test")
async def stress_test(request: StressTestRequest):
    agent = StressTestAgent(settings.agents_dir)
    return await agent.run(
        request,
        itinerary=request.itinerary,
        flights=request.flights,
        visa=request.visa,
        weather=request.weather,
    )
