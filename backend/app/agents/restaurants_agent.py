import logging
from urllib.parse import quote_plus

from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition

logger = logging.getLogger(__name__)


class RestaurantsAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "restaurants"))

    async def run(self, request: TravelSearchRequest) -> dict:
        if request.budget_usd and request.budget_usd < 1000:
            budget_tier = "budget"
        elif request.budget_usd and request.budget_usd < 3000:
            budget_tier = "mid-range"
        else:
            budget_tier = "luxury"

        interests_str = (
            ", ".join(request.interests) if request.interests else "general sightseeing"
        )

        prompt = (
            f"Recommend restaurants for travelers visiting {request.destination} "
            f"(always include the country, e.g. 'Tokyo, Japan' or 'Paris, France').\n"
            f"Number of travelers: {request.num_travelers}\n"
            f"Traveler interests: {interests_str}\n"
            f"Overall budget tier: {budget_tier} (budget_usd={request.budget_usd})\n"
            f"Return 3-5 restaurants per category: breakfast, lunch, dinner, "
            f"street_food_and_late_night. Mix price ranges within each category. "
            f"Include a brief dining_culture_note about local customs."
        )

        data = await self.execute(prompt)

        if data.get("error"):
            return data

        # Ensure every restaurant has a valid booking_url using Google Maps search format
        destination = request.destination
        categories = ["breakfast", "lunch", "dinner", "street_food_and_late_night"]
        restaurants_map = data.get("restaurants", {})
        for category in categories:
            for restaurant in restaurants_map.get(category, []):
                url = restaurant.get("booking_url", "")
                if not url or not url.startswith("http"):
                    name = restaurant.get("name", "")
                    query = quote_plus(f"{name} {destination}")
                    restaurant["booking_url"] = (
                        f"https://www.google.com/maps/search/{query}"
                    )

        return data
