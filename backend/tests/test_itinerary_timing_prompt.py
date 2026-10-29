"""The itinerary prompts ask for what the client-side scheduler needs:
a duration on every slot and coordinates on every slot naming a place."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.agents.itinerary_agent import ItineraryAgent
from app.schemas.request import TravelSearchRequest

BASE = {
    "origin": "New York, USA",
    "destination": "Tokyo, Japan",
    "departure_date": "2026-08-10",
    "return_date": "2026-08-17",
    "nationality": "American",
}

DURATION = "duration_hours on every slot"
COORDS = (
    "lat/lng coordinates (decimal degrees) on every slot; for slots without a "
    "specific place, use approximate coordinates of the neighbourhood or the hotel"
)


async def _prompt(**overrides) -> str:
    agent = ItineraryAgent.__new__(ItineraryAgent)
    agent.execute = AsyncMock(return_value={"days": []})
    req = TravelSearchRequest(**{**BASE, **overrides})
    await agent.run(req, destinations=req.destinations)
    return agent.execute.call_args[0][0]


@pytest.mark.anyio
async def test_single_city_prompt_asks_for_durations_and_coordinates():
    prompt = await _prompt()
    assert DURATION in prompt
    assert COORDS in prompt


@pytest.mark.anyio
async def test_multi_city_prompt_asks_for_durations_and_coordinates():
    prompt = await _prompt(destinations=["Tokyo, Japan", "Kyoto, Japan"])
    assert "MULTI-CITY" in prompt
    assert DURATION in prompt
    assert COORDS in prompt


def test_agent_definition_requires_durations_and_coordinates():
    text = (Path(__file__).parents[2] / ".agents" / "itinerary.md").read_text()
    assert "`duration_hours`: required on every slot" in text
    assert (
        "`lat`, `lng`: required on every slot; for slots without a specific place, "
        "use approximate coordinates of the neighbourhood or the hotel" in text
    )
