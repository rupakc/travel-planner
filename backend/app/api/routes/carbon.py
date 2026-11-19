"""Trip carbon footprint (docs/Carbon-Footprint.md).

``POST /api/carbon/trip`` — pure computation (services/carbon.py): no LLM, no
storage. The one network read is the crawler's carbon data
(services/carbon_live.py: newer DESNZ factors, grid intensity), only when
``CRAWLER_ENABLED`` and cached; off, down or slow, the answer is exactly the
committed-table one. Anonymous calls are fine; its own ``carbon`` rate bucket
(per user or client IP), body capped at 512 KB in main.py. 404 when
``CARBON_FOOTPRINT_ENABLED`` is false.
"""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, model_validator

from ...core.config import settings
from ...services import carbon, carbon_live, crawler_client

router = APIRouter()


class CarbonTripRequest(BaseModel):
    # Trip fields as on the search form: origin, destination, destinations,
    # destination_nights, departure_date, return_date, num_travelers
    search: dict[str, Any] = Field(default_factory=dict)
    # A plan's selections (flight, flights, hotel, getting_around, activities)
    selections: dict[str, Any] | None = None
    # Or a search-result summary: {flights, hotels, itinerary} section data
    results: dict[str, Any] | None = None
    # The day-by-day plan ({days: [{slots: [{lat, lng, activity}]}]})
    itinerary: dict[str, Any] | None = None
    diet: Literal["mixed", "meat_heavy", "pescatarian", "vegetarian", "vegan"] = "mixed"
    cabin: Literal["economy", "premium_economy", "business", "first"] | None = None
    rooms: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def _one_input(self):
        if (self.selections is None) == (self.results is None):
            raise ValueError("send exactly one of selections or results")
        return self


@router.post("/carbon/trip")
async def carbon_trip(body: CarbonTripRequest) -> dict:
    if not settings.carbon_footprint_enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    req = body.model_dump()
    live = None
    if crawler_client.configured():
        countries = await run_in_threadpool(carbon.stay_countries, req)
        live = await carbon_live.fetch(carbon.factors(), countries)
    # Local DB lookups (airports, places): off the event loop
    return await run_in_threadpool(carbon.compute, req, live)
