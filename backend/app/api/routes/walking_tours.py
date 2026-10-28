from fastapi import APIRouter

from ...agents.walking_tours_agent import WalkingToursAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest

router = APIRouter()


@router.post("/walking-tours")
async def get_walking_tours(request: TravelSearchRequest):
    """Find free walking tours at the destination from crawled provider listings."""
    agent = WalkingToursAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
