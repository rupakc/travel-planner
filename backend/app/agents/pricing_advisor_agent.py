from datetime import date

from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
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
        return await self.execute(prompt)
