from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition


class ChecklistAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "checklist"))

    async def run(self, request: TravelSearchRequest) -> dict:
        trip_days = (
            (request.return_date - request.departure_date).days
            if request.return_date
            else 7
        )

        prompt = (
            f"Trip details:\n"
            f"  Origin: {request.origin}\n"
            f"  Destination: {request.destination}\n"
            f"  Departure date: {request.departure_date}\n"
            f"  Return date: {request.return_date or 'open-ended'}\n"
            f"  Duration: {trip_days} night(s)\n"
            f"  Travelers: {request.traveler_context}\n"
            f"  Nationality: {request.nationality}\n"
            f"  Interests: {', '.join(request.interests) if request.interests else 'general'}\n"
            f"  Accessibility needs: {', '.join(request.accessibility_needs) if request.accessibility_needs else 'none'}\n\n"
            "Generate a personalized pre-departure checklist for this trip."
        )
        return await self.execute(prompt)
