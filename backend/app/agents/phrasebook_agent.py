import logging

from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition

logger = logging.getLogger(__name__)


class PhrasebookAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "phrasebook"))

    async def run(self, request: TravelSearchRequest) -> dict:
        interests_str = (
            ", ".join(request.interests) if request.interests else "general sightseeing"
        )
        prompt = (
            f"Generate contextual phrasebook for {request.destination} "
            f"(identify the country and use the full location, e.g. 'Tokyo, Japan').\n"
            f"Traveler interests: {interests_str}.\n"
            f"Generate 35-50 phrases matching their activities.\n"
            f"Include: essentials, transit, food, emergency, plus extra phrases for their interests.\n"
            f"Bias category distribution: add more phrases for categories that match "
            f"the traveler's interests ({interests_str}).\n"
            f"Always include at least 5 essentials, 4 transit, 3 emergency, and 3 courtesy phrases."
        )
        return await self.execute(prompt)
