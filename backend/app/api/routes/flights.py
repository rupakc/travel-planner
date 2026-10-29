from fastapi import APIRouter, Depends, HTTPException

from ...agents.flights_agent import FlightsAgent
from ...core.auth import get_current_user
from ...core.config import settings
from ...schemas.request import FlightFilteredSearchRequest, TravelSearchRequest
from ...services.serp_flights import search_calendar
from ...services.verification import attach_verification

router = APIRouter()


@router.post("/flights")
async def get_flights(request: TravelSearchRequest):
    agent = FlightsAgent(agents_dir=settings.agents_dir)
    return await agent.run(request)


@router.post("/flights/filtered")
async def get_flights_filtered(request: FlightFilteredSearchRequest):
    """Run a flights-only search with optional filters, including URL enrichment."""
    agent = FlightsAgent(agents_dir=settings.agents_dir)
    filters = {}
    if request.max_stops is not None:
        filters["max_stops"] = request.max_stops
    if request.max_price_usd is not None:
        filters["max_price_usd"] = request.max_price_usd
    if request.departure_time_earliest:
        filters["departure_time_earliest"] = request.departure_time_earliest
    if request.departure_time_latest:
        filters["departure_time_latest"] = request.departure_time_latest
    if request.arrival_time_earliest:
        filters["arrival_time_earliest"] = request.arrival_time_earliest
    if request.arrival_time_latest:
        filters["arrival_time_latest"] = request.arrival_time_latest

    result = await agent.run(request, filters=filters if filters else None)
    if not result.get("error"):
        result = await agent.enrich(result)
    # Final (non-pending) label so the chip survives the section replacement
    return attach_verification("flights", result, request)


@router.post("/flights/fare-calendar")
async def get_fare_calendar(
    request: TravelSearchRequest, _user: dict = Depends(get_current_user)
):
    """Cheapest live fare for departure dates ±3 days (same trip length)."""
    if request.is_multi_city:
        raise HTTPException(
            status_code=422,
            detail="Fare calendar is only available for single-destination trips.",
        )
    if not settings.serpapi_key:
        raise HTTPException(
            status_code=503,
            detail="Fare calendar needs live flight data, which isn't configured.",
        )
    return await search_calendar(settings.serpapi_key, request)
