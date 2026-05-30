"""Day trips agent — recommends day trips within 3 hours of the base city."""

from __future__ import annotations

import logging

from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition

logger = logging.getLogger(__name__)


class DayTripsAgent(BaseAgent):
    def __init__(self, agents_dir: str) -> None:
        super().__init__(load_agent_definition(agents_dir, "day_trips"))

    async def run(self, request: TravelSearchRequest) -> dict:
        interests_str = (
            ", ".join(request.interests) if request.interests else "general sightseeing"
        )
        nights = (
            (request.return_date - request.departure_date).days
            if request.return_date and request.departure_date
            else 7
        )
        prompt = (
            f"Suggest 4-6 day trips from {request.destination} (identify and include the country, "
            f"e.g. 'Tokyo, Japan'). "
            f"Interests: {interests_str}. "
            f"Duration: {nights} nights. "
            f"{request.traveler_context}."
        )
        return await self.execute(prompt)
