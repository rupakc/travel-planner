from fastapi import APIRouter

from ...agents.sim_agent import SimAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest

router = APIRouter()


@router.post("/sim")
async def get_sim(request: TravelSearchRequest):
    agent = SimAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
