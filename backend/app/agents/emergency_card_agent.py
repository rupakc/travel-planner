from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition


def _same_country(nationality: str, destination: str) -> bool:
    """Very rough heuristic — catches obvious home-country cases."""
    nat = nationality.lower()
    # Match against each comma-separated component so city-first strings
    # like "San Francisco, USA" resolve by their country part.
    parts = [p.strip() for p in destination.lower().split(",")]
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
    return any(
        nat.startswith(n) and any(p.startswith(d) for p in parts) for n, d in pairs
    )


def build_emergency_prompt(request: TravelSearchRequest) -> str:
    """Build the user prompt — multi-city trips must cover EVERY stop."""
    if request.is_multi_city:
        cities = request.destinations
        home_cities = [c for c in cities if _same_country(request.nationality, c)]
        prompt = (
            f"MULTI-CITY trip — cities in order: {' → '.join(cities)}\n"
            f"Traveler nationality: {request.nationality}\n"
        )
        if home_cities:
            prompt += (
                "Home-country cities (embassy null + home_country_note for these): "
                + ", ".join(home_cities)
                + "\n"
            )
        prompt += (
            "Return the MULTI-CITY format: a top-level 'cities' array with one "
            "complete entry per city above, in the same order. Do NOT skip any "
            "city — every stop needs its own emergency numbers, embassy, "
            "hospitals, phrases and laws.\n"
            "Generate the emergency reference card for this traveler."
        )
        return prompt

    home_country = _same_country(request.nationality, request.destination)
    prompt = (
        f"Destination: {request.destination}\n"
        f"Traveler nationality: {request.nationality}\n"
    )
    if home_country:
        prompt += "Note: The traveler is visiting their home country — skip the embassy section (set embassy to null) and set home_country_note.\n"
    prompt += "Generate the emergency reference card for this traveler."
    return prompt


class EmergencyCardAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "emergency_card"))

    async def run(self, request: TravelSearchRequest) -> dict:
        result = await self.execute(build_emergency_prompt(request))
        return result
