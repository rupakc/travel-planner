from ..schemas.request import DiscoveryRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition
from .static_results import find_visa_row


class DiscoveryAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "discovery"))

    async def run(self, request: DiscoveryRequest) -> dict:
        trip_days = (
            (request.return_date - request.departure_date).days
            if request.return_date
            else 7
        )
        interest_str = (
            ", ".join(request.interests) if request.interests else "general tourism"
        )
        prompt = (
            f"Traveler profile:\n"
            f"  Departure city: {request.origin}\n"
            f"  Nationality: {request.nationality}\n"
            f"  Budget: {'$' + str(int(request.budget_usd)) if request.budget_usd else 'flexible'}\n"
            f"  Trip duration: {trip_days} nights ({request.departure_date} to {request.return_date or 'open-ended'})\n"
            f"  Travelers: {request.adults} adult(s)"
            + (f", {request.children} child(ren)" if request.children else "")
            + (f", {request.seniors} senior(s)" if request.seniors else "")
            + "\n"
            f"  Interests: {interest_str}\n\n"
            "Suggest 5 destinations that best match this profile. Vary by region when possible."
        )
        result = await self.execute(prompt)

        # Override LLM visa guesses with authoritative _VISA_TABLE data
        for dest in result.get("destinations", []):
            place = ", ".join(p for p in (dest.get("city"), dest.get("country")) if p)
            visa_info = find_visa_row(request.nationality, place)
            if visa_info:
                dest["visa_type"] = visa_info.get(
                    "visa_type", dest.get("visa_type", "verify")
                )
                dest["visa_verified"] = True
            else:
                dest["visa_verified"] = False  # UI shows amber "Verify" badge
        return result
