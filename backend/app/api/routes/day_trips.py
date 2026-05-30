from fastapi import APIRouter

from ...agents.day_trips_agent import DayTripsAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest

router = APIRouter()


@router.post("/day-trips")
async def get_day_trips(request: TravelSearchRequest):
    agent = DayTripsAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
