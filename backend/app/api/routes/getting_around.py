from fastapi import APIRouter
from ...schemas.request import TravelSearchRequest
from ...agents.getting_around_agent import GettingAroundAgent
from ...core.config import settings

router = APIRouter()


@router.post("/getting-around")
async def get_getting_around(request: TravelSearchRequest):
    agent = GettingAroundAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
