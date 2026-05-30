import logging

from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition

logger = logging.getLogger(__name__)


class JetLagAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "jet_lag"))

    async def run(self, request: TravelSearchRequest) -> dict:
        prompt = (
            f"Generate a jet lag prevention and recovery plan for a traveler flying from "
            f"{request.origin} to {request.destination} "
            f"(identify origin and destination countries, e.g. 'New York, USA' → 'Tokyo, Japan').\n"
            f"Departure date: {request.departure_date}.\n"
            f"Calculate the time zone difference between {request.origin} and {request.destination}.\n"
            f"If the absolute time difference is less than 4 hours, return "
            f'{"{"}"skip": true, "message": "Time difference small - jet lag unlikely."{"}"} '
            f"and nothing else.\n"
            f"Otherwise, return the full jet lag plan with preparation steps for the days before "
            f"departure, on-the-flight advice, and first-day-at-destination tips."
        )
        return await self.execute(prompt)
