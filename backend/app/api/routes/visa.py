from fastapi import APIRouter

from ...agents.visa_agent import VisaAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest

router = APIRouter()


@router.post("/visa")
async def get_visa(request: TravelSearchRequest):
    agent = VisaAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
