from fastapi import APIRouter
from ...schemas.request import TravelSearchRequest, FlightFilteredSearchRequest
from ...agents.flights_agent import FlightsAgent
from ...core.config import settings

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
    return result
