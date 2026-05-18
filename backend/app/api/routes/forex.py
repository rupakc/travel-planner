from fastapi import APIRouter

from ...agents.forex_agent import ForexAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest

router = APIRouter()


@router.post("/forex")
async def get_forex(request: TravelSearchRequest):
    agent = ForexAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
