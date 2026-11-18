from datetime import timedelta

from ..schemas.request import TravelSearchRequest
from ..services import crawler_client, crawler_facts
from .base_agent import BaseAgent, locale_kw
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
            prompt += (
                f"{request.multi_city_context}\n"
                f"MANDATORY COVERAGE: 2-4 events for EACH city "
                f"({', '.join(request.destinations)}) — never skip a city; "
                "match each city's events to the dates the traveler is there.\n"
            )
        prompt += (
            "Return festivals, concerts, exhibitions, sports, markets and "
            "seasonal happenings overlapping these dates, plus any disruptions "
            "worth planning around."
        )
        if not crawler_client.configured():
            return await self.execute(prompt, **locale_kw(request))
        # Public holidays during the trip from the crawler: their own
        # attributed list (docs/Crawler-Data.md); only open-licence ones are
        # also given to the model as context
        holidays = await crawler_facts.trip_holidays(request)
        if holidays:
            prompt += crawler_facts.holidays_prompt(holidays)
        result = await self.execute(prompt, **locale_kw(request))
        return crawler_facts.apply_holidays(result, holidays)
