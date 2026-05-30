from fastapi import APIRouter

from ...agents.checklist_agent import ChecklistAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest

router = APIRouter()


@router.post("/checklist")
async def get_checklist(request: TravelSearchRequest):
    agent = ChecklistAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)
