import asyncio

from ..schemas.request import TravelSearchRequest
from ..services import crawler_client, crawler_facts
from .base_agent import BaseAgent, locale_kw
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
        if not crawler_client.configured():
            return await self.execute(
                build_emergency_prompt(request), **locale_kw(request)
            )
        # Official numbers, embassies and medical lists from the crawler,
        # fetched while the model writes the card (docs/Crawler-Data.md)
        result, facts = await asyncio.gather(
            self.execute(build_emergency_prompt(request), **locale_kw(request)),
            emergency_facts_for(request),
        )
        return apply_emergency_facts(result, facts, request)


def _stops(request: TravelSearchRequest) -> list[str]:
    return (
        list(request.destinations) if request.is_multi_city else [request.destination]
    )


async def emergency_facts_for(request: TravelSearchRequest) -> dict[str, dict | None]:
    """Crawler facts per stop (keyed by the stop's text); a stop's value is
    None when the crawler did not answer or the country is unknown."""
    nat = crawler_facts.country_for_nationality(request.nationality)
    stops = _stops(request)
    codes = [crawler_facts.country_for_place(s) for s in stops]
    got = await asyncio.gather(
        *(
            crawler_facts.emergency_facts(code, nat, stop) if code else _none()
            for stop, code in zip(stops, codes)
        )
    )
    return dict(zip(stops, got))


async def _none():
    return None


def apply_emergency_facts(
    result: dict, facts: dict[str, dict | None], request: TravelSearchRequest
) -> dict:
    if not isinstance(result, dict) or result.get("error"):
        return result
    if isinstance(result.get("cities"), list):
        by_city = {crawler_facts.fold_place(k): v for k, v in facts.items()}
        for entry in result["cities"]:
            if not isinstance(entry, dict):
                continue
            city = str(entry.get("city") or "")
            f = by_city.get(crawler_facts.fold_place(city))
            if f is None:
                # The model may shorten "Paris, France" to "Paris"
                f = next(
                    (
                        v
                        for k, v in facts.items()
                        if crawler_facts.fold_place(k.split(",")[0])
                        == crawler_facts.fold_place(city.split(",")[0])
                    ),
                    None,
                )
            crawler_facts.apply_emergency(
                entry, f, home_country=_same_country(request.nationality, city)
            )
        return result
    return crawler_facts.apply_emergency(
        result,
        facts.get(request.destination),
        home_country=_same_country(request.nationality, request.destination),
    )
