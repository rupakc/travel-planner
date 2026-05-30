from fastapi import APIRouter
from pydantic import BaseModel

from ...agents.content_import_agent import ContentImportAgent
from ...core.config import settings

router = APIRouter()


class ContentImportRequest(BaseModel):
    url: str


@router.post("/content-import")
async def import_content(request: ContentImportRequest):
    agent = ContentImportAgent(agents_dir=settings.agents_dir)
    return await agent.run_from_url(request.url)
