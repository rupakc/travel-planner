import json

from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition


class ItineraryAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "itinerary"))

    async def run(
        self, request: TravelSearchRequest, activities: dict = None, hotels: dict = None
    ) -> dict:
        nights = (
            (request.return_date - request.departure_date).days
            if request.return_date
            else 7
        )
        interests_str = (
            ", ".join(request.interests) if request.interests else "general travel"
        )

        activities_summary = ""
        if activities and activities.get("results"):
            top = activities["results"][:12]
            brief = [
                {
                    "name": a.get("name"),
                    "category": a.get("category"),
                    "duration_hours": a.get("duration_hours"),
                    "price_usd": a.get("price_usd"),
                    "location": a.get("location"),
                }
                for a in top
            ]
            activities_summary = json.dumps(brief)

        hotel_name = "your hotel"
        if hotels and hotels.get("results"):
            hotel_name = hotels["results"][0].get("name", "your hotel")

        prompt = (
            f"Create a day-by-day travel itinerary for {request.destination} (identify the country).\n"
            f"Traveling from: {request.origin}\n"
            f"Trip dates: {request.departure_date} to {request.return_date} ({nights} nights)\n"
            f"Travelers: {request.num_travelers}\n"
            f"Interests: {interests_str}\n"
            f"Hotel: {hotel_name}\n\n"
            f"Available activities:\n{activities_summary}\n\n"
            f"Create a {nights + 1}-day itinerary (arrival day through departure day).\n"
            f"Each day: exactly 3 time slots (morning, afternoon, evening).\n"
            f"Day 1 = arrival from {request.origin}. Last day = departure back to {request.origin}.\n"
            f"Include daily_estimated_cost_usd and total_estimated_cost_usd.\n"
            f"Group geographically close activities on the same day.\n"
            f"Include meal costs (~$50/person/day). Costs are PER PERSON."
        )
        return await self.execute(prompt)
