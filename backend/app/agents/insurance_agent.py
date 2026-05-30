import logging

from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition

logger = logging.getLogger(__name__)


class InsuranceAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "insurance"))

    async def run(self, request: TravelSearchRequest) -> dict:
        nights = (
            (request.return_date - request.departure_date).days
            if request.return_date
            else 7
        )
        interests_str = (
            ", ".join(request.interests) if request.interests else "general sightseeing"
        )
        traveler_context_parts = []
        if request.num_travelers and request.num_travelers > 1:
            traveler_context_parts.append(f"{request.num_travelers} travelers")
        if request.budget_usd:
            traveler_context_parts.append(
                f"total trip budget ~${request.budget_usd:,} USD"
            )
        traveler_context = (
            ", ".join(traveler_context_parts)
            if traveler_context_parts
            else "1 traveler"
        )

        prompt = (
            f"Assess travel insurance needs for:\n"
            f"Destination: {request.destination} (identify the country and use the full location, e.g. 'Bali, Indonesia')\n"
            f"Origin: {request.origin}\n"
            f"Trip duration: {nights} nights (from {request.departure_date}"
            + (f" to {request.return_date}" if request.return_date else "")
            + ")\n"
            f"Traveler interests / planned activities: {interests_str}\n"
            f"Traveler context: {traveler_context}\n\n"
            f"Determine the risk level, list the specific risk factors for this trip, "
            f"and recommend the most appropriate insurance coverage type. "
            f"Tailor adventure_sports_note and watch_out_for items to the planned activities."
        )
        return await self.execute(prompt)
