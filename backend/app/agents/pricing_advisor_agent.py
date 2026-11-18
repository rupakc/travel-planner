from datetime import date

from ..schemas.request import TravelSearchRequest
from ..services import crawler_client, crawler_facts
from .base_agent import BaseAgent, locale_kw
from .loader import load_agent_definition


class PricingAdvisorAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "pricing_advisor"))

    async def run(
        self,
        request: TravelSearchRequest,
        flights: dict | None = None,
        avg_price: float | None = None,
    ) -> dict:
        days_until = (request.departure_date - date.today()).days

        price_context = ""
        if avg_price is not None:
            price_context = (
                f"Current average price for this route: ${avg_price:.0f} USD\n"
            )
        else:
            price_context = "Current flight prices: not available\n"

        prompt = (
            f"Route: {request.origin} → {request.destination}\n"
            f"Departure date: {request.departure_date}\n"
            f"Days until departure: {days_until}\n"
            f"{price_context}"
            "Provide flight booking timing advice based on historical pricing patterns for this route."
        )
        if not crawler_client.configured():
            return await self.execute(prompt, **locale_kw(request))
        # Typical cached fares for the route and month (a fare cache's view,
        # never a live price), as context and a labelled line in the banner
        fares = await crawler_facts.typical_fares(
            request.origin_iata,
            request.destination_iata,
            request.departure_date.strftime("%Y-%m"),
        )
        if fares:
            prompt += crawler_facts.fares_prompt(fares)
        result = await self.execute(prompt, **locale_kw(request))
        if fares and isinstance(result, dict) and not result.get("error"):
            result["typical_fares"] = fares
            result["crawler_sources"] = [fares["source"]]
        return result
