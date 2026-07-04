from datetime import timedelta

from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition


class EventsAgent(BaseAgent):
    """Finds festivals, concerts, exhibitions and seasonal happenings during the trip."""

    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "events"))

    async def run(self, request: TravelSearchRequest) -> dict:
        dep = request.departure_date
        ret = request.return_date or (dep + timedelta(days=7))
        interests_str = (
            ", ".join(request.interests) if request.interests else "general travel"
        )

        prompt = (
            f"Find local events in {request.destination_label} "
            f"(identify the country).\n"
            f"Trip dates: {dep} ({dep.strftime('%A')}) to {ret} ({ret.strftime('%A')})"
            f" — month: {dep.strftime('%B')}\n"
            f"Traveler interests: {interests_str}\n"
            f"Travelers: {request.traveler_context}\n"
        )
        if request.multi_city_context:
            prompt += f"{request.multi_city_context}\n"
        prompt += (
            "Return festivals, concerts, exhibitions, sports, markets and "
            "seasonal happenings overlapping these dates, plus any disruptions "
            "worth planning around."
        )
        return await self.execute(prompt)
