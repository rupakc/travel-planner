from fastapi import APIRouter

from ...agents.tips_agent import TipsAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest

router = APIRouter()


@router.post("/tips")
async def get_tips(request: TravelSearchRequest):
    agent = TipsAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
