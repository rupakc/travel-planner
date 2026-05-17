from fastapi import APIRouter
from ...schemas.request import TravelSearchRequest, HotelFilteredSearchRequest
from ...agents.hotels_agent import HotelsAgent
from ...core.config import settings

router = APIRouter()


@router.post("/hotels")
async def get_hotels(request: TravelSearchRequest):
    agent = HotelsAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)


@router.post("/hotels/filtered")
async def get_hotels_filtered(request: HotelFilteredSearchRequest):
    """Run a hotels-only search with optional filters, including URL enrichment."""
    agent = HotelsAgent(agents_dir=settings.agents_dir)
    filters = {}
    if request.num_beds is not None:
        filters["num_beds"] = request.num_beds
    if request.max_price_per_night_usd is not None:
        filters["max_price_per_night_usd"] = request.max_price_per_night_usd
    if request.wifi_quality:
        filters["wifi_quality"] = request.wifi_quality
    if request.max_distance_from_center_km is not None:
        filters["max_distance_from_center_km"] = request.max_distance_from_center_km
    if request.private_washroom is not None:
        filters["private_washroom"] = request.private_washroom

    result = await agent.run(request, filters=filters if filters else None)
    if not result.get("error"):
        result = await agent.enrich(result)
    return result
