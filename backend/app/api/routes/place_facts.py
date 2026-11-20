"""``POST /api/place-facts``: the place facts section on its own
(docs/Place-Facts.md). Same body as ``/api/search``; light_ai bucket."""

from fastapi import APIRouter, HTTPException

from ...agents.place_facts_agent import PlaceFactsAgent
from ...core.config import settings
from ...schemas.request import TravelSearchRequest
from ...services.verification import attach_verification

router = APIRouter()


@router.post("/place-facts")
async def get_place_facts(request: TravelSearchRequest):
    """Facts about each destination, its region and its country: crawler
    facts with their sources, AI-suggested facts (unverified, no source) for
    the groups the crawler left empty."""
    if not settings.place_facts_enabled:
        raise HTTPException(status_code=404, detail="place_facts_disabled")
    agent = PlaceFactsAgent(agents_dir=settings.agents_dir)
    result = await agent.run(request)
    return attach_verification("facts", result, request)
