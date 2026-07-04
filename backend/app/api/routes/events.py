from fastapi import APIRouter

from ...agents.events_agent import EventsAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest

router = APIRouter()


@router.post("/events")
async def get_events(request: TravelSearchRequest):
    """Find festivals, concerts, exhibitions and seasonal happenings during the trip."""
    agent = EventsAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
