from fastapi import APIRouter
from ...schemas.request import TravelSearchRequest
from ...agents.tips_agent import TipsAgent
from ...core.config import settings

router = APIRouter()


@router.post("/tips")
async def get_tips(request: TravelSearchRequest):
    agent = TipsAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
