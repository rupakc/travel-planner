from fastapi import APIRouter

from ...agents.restaurants_agent import RestaurantsAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest

router = APIRouter()


@router.post("/restaurants")
async def get_restaurants(request: TravelSearchRequest):
    agent = RestaurantsAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
