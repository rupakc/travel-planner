from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...agents.layover_agent import LayoverAgent
from ...core.config import settings

router = APIRouter()


class LayoverRequest(BaseModel):
    city: str = Field(..., min_length=2, description="Layover city, e.g. 'Doha, Qatar'")
    duration_hours: float = Field(..., gt=0, le=48, description="Layover length")
    nationality: str = Field(..., min_length=2, description="Traveler nationality")
    airport: str | None = Field(None, description="Airport IATA code, e.g. DOH")
    arrival_time: str | None = Field(
        None, pattern=r"^\d{2}:\d{2}$", description="Arrival time HH:MM (local)"
    )
    interests: list[str] = Field(default_factory=list)


@router.post("/layover")
async def optimize_layover(request: LayoverRequest):
    """Turn a long layover into a mini-plan (exit feasibility, transit visa, itinerary)."""
    agent = LayoverAgent(agents_dir=settings.agents_dir)
    return await agent.run(
        city=request.city,
        duration_hours=request.duration_hours,
        nationality=request.nationality,
        airport=request.airport,
        arrival_time=request.arrival_time,
        interests=request.interests,
    )
