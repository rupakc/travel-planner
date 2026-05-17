from fastapi import APIRouter
from ...schemas.request import TravelSearchRequest, ActivityFilteredSearchRequest
from ...agents.activities_agent import ActivitiesAgent
from ...core.config import settings

router = APIRouter()


@router.post("/activities")
async def get_activities(request: TravelSearchRequest):
    agent = ActivitiesAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)


@router.post("/activities/filtered")
async def get_activities_filtered(request: ActivityFilteredSearchRequest):
    """Run an activities-only search with optional filters, including URL enrichment."""
    agent = ActivitiesAgent(agents_dir=settings.agents_dir)
    filters = {}
    if request.filter_interests:
        filters["filter_interests"] = request.filter_interests
    if request.max_price_usd is not None:
        filters["max_price_usd"] = request.max_price_usd
    if request.available_from:
        filters["available_from"] = request.available_from
    if request.available_to:
        filters["available_to"] = request.available_to
    if request.min_rating is not None:
        filters["min_rating"] = request.min_rating

    result = await agent.run(request, filters=filters if filters else None)
    if not result.get("error"):
        result = await agent.enrich(result)
    return result
