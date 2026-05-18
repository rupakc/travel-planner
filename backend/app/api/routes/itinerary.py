from fastapi import APIRouter

from ...agents.itinerary_agent import ItineraryAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest

router = APIRouter()


@router.post("/itinerary")
async def get_itinerary(request: TravelSearchRequest):
    agent = ItineraryAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
