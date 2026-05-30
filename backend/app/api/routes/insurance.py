from fastapi import APIRouter

from ...agents.insurance_agent import InsuranceAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest

router = APIRouter()


@router.post("/insurance")
async def get_insurance(request: TravelSearchRequest):
    agent = InsuranceAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
