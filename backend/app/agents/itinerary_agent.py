import json

from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition


class ItineraryAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "itinerary"))

    async def run(
        self,
        request: TravelSearchRequest,
        activities: dict = None,
        hotels: dict = None,
        destinations: list[str] | None = None,
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

        is_multi = bool(destinations and len(destinations) > 1)

        if is_multi:
            n = len(destinations)
            base = max(2, nights // n)
            extra = nights - base * n
            city_nights = [base] * n
            for i in range(extra):
                city_nights[(n // 2 + i) % n] += 1

            city_plan_lines = []
            current_day = 1
            for city, cn in zip(destinations, city_nights):
                end_day = current_day + cn
                city_plan_lines.append(
                    f"- {city}: Days {current_day}–{end_day - 1} ({cn} nights)"
                )
                current_day = end_day

            multi_city_block = (
                "\n\nThis is a MULTI-CITY trip."
                "\n\nSTEP 1 — OPTIMIZE CITY ORDER FIRST:"
                f"\nThe requested cities are: {', '.join(destinations)}."
                "\nBefore building the itinerary, reorder these cities to minimize total travel "
                "distance and cost (avoid backtracking across continents or long detours). "
                "Use geographic proximity — neighbouring cities should be visited consecutively. "
                "Apply the optimized order to all day assignments below. "
                "If the first city was specified as the starting point by the user, keep it first.\n"
                "\nSTEP 2 — CITY ALLOCATION (adjust days to match your optimized order):\n"
                + "\n".join(city_plan_lines)
                + "\n\nFor each day:\n"
                '- Add a \'city\' field to the day object (e.g. "city": "Paris")\n'
                "- Add a 'city' field to each slot object matching the day's city\n"
                "- Between cities, insert a travel day:\n"
                "    morning: 'Travel from [City A] to [City B]' (train/flight — use the cheapest realistic option)\n"
                "    afternoon: 'Arrive [City B], check in, light walk'\n"
                "    evening: 'First dinner in [City B] — [local dish]'\n"
                "- Keep all activities geographically within each day's city\n"
                "- Add lat/lng coordinates (decimal degrees) to every slot\n"
            )
        else:
            multi_city_block = (
                "\nAdd lat/lng coordinates (decimal degrees) to every slot.\n"
            )

        prompt = (
            f"Create a day-by-day travel itinerary for {request.destination} (identify the country).\n"
            f"Traveling from: {request.origin}\n"
            f"Trip dates: {request.departure_date} to {request.return_date} ({nights} nights)\n"
            f"Travelers: {request.traveler_context}\n"
            f"Interests: {interests_str}\n"
            f"Hotel: {hotel_name}\n\n"
            f"Available activities:\n{activities_summary}\n\n"
            f"Create a {nights + 1}-day itinerary (arrival day through departure day).\n"
            f"Each day: exactly 3 time slots (morning, afternoon, evening).\n"
            f"Day 1 = arrival from {request.origin}. Last day = departure back to {request.origin}.\n"
            f"Include daily_estimated_cost_usd and total_estimated_cost_usd.\n"
            f"Group geographically close activities on the same day.\n"
            f"Include meal costs (~$50/person/day). Costs are PER PERSON."
            + multi_city_block
        )
        result = await self.execute(prompt)
        if result and not result.get("error"):
            result = self._add_transit_times(result)
        return result

    def _add_transit_times(self, itinerary: dict) -> dict:
        try:
            from ..services.transit_estimator import estimate_transit

            for day in itinerary.get("days", []):
                slots = day.get("slots", [])
                for i in range(len(slots) - 1):
                    slot, nxt = slots[i], slots[i + 1]
                    lat1 = slot.get("lat")
                    lng1 = slot.get("lng")
                    lat2 = nxt.get("lat")
                    lng2 = nxt.get("lng")
                    if all(v is not None for v in [lat1, lng1, lat2, lng2]):
                        t = estimate_transit(
                            float(lat1), float(lng1), float(lat2), float(lng2)
                        )
                        slot["transit_to_next_minutes"] = t["minutes"]
                        slot["transit_to_next_mode"] = t["mode"]
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("Transit enrichment failed: %s", exc)
        return itinerary
