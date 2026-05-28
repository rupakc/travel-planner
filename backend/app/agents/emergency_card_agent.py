from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition


def _same_country(nationality: str, destination: str) -> bool:
    """Very rough heuristic — catches obvious home-country cases."""
    nat = nationality.lower()
    dest = destination.lower()
    pairs = [
        ("american", "usa"),
        ("american", "united states"),
        ("british", "uk"),
        ("british", "united kingdom"),
        ("british", "england"),
        ("french", "france"),
        ("german", "germany"),
        ("italian", "italy"),
        ("japanese", "japan"),
        ("chinese", "china"),
        ("indian", "india"),
        ("australian", "australia"),
        ("canadian", "canada"),
        ("singaporean", "singapore"),
        ("thai", "thailand"),
    ]
    return any(nat.startswith(n) and dest.startswith(d) for n, d in pairs)


class EmergencyCardAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "emergency_card"))

    async def run(self, request: TravelSearchRequest) -> dict:
        home_country = _same_country(request.nationality, request.destination)
        prompt = (
            f"Destination: {request.destination}\n"
            f"Traveler nationality: {request.nationality}\n"
        )
        if home_country:
            prompt += "Note: The traveler is visiting their home country — skip the embassy section (set embassy to null) and set home_country_note.\n"
        prompt += "Generate the emergency reference card for this traveler."
        result = await self.execute(prompt)
        return result
