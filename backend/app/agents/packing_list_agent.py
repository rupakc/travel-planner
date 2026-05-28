from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition


class PackingListAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "packing_list"))

    async def run(
        self,
        request: TravelSearchRequest,
        weather: dict | None = None,
        activities: dict | None = None,
    ) -> dict:
        trip_days = (
            (request.return_date - request.departure_date).days
            if request.return_date
            else 7
        )

        # Summarise weather (don't pass raw JSON)
        weather_summary = "No weather data available"
        if weather and not weather.get("error") and weather.get("days"):
            days = weather["days"]
            poor_days = sum(1 for d in days if d.get("is_poor"))
            temps = [d["temp_high_c"] for d in days if d.get("temp_high_c") is not None]
            avg_high = round(sum(temps) / len(temps)) if temps else None
            if avg_high is not None:
                weather_summary = f"{len(days)} days, avg high {avg_high}°C, {poor_days} rainy/poor day(s)"
            else:
                weather_summary = f"{len(days)} days, {poor_days} rainy/poor day(s)"

        # Summarise activities (don't pass raw JSON)
        activity_summary = "No specific activities booked"
        if activities and not activities.get("error") and activities.get("results"):
            act_names = [
                a.get("name", "") for a in activities["results"][:8] if a.get("name")
            ]
            activity_summary = (
                ", ".join(act_names) if act_names else "General sightseeing"
            )

        prompt = (
            f"Trip details:\n"
            f"  Destination: {request.destination}\n"
            f"  Duration: {trip_days} nights ({request.departure_date} to {request.return_date or 'open-ended'})\n"
            f"  Travelers: {request.traveler_context}\n"
            f"  Interests: {', '.join(request.interests) if request.interests else 'general'}\n"
            f"  Weather: {weather_summary}\n"
            f"  Planned activities: {activity_summary}\n\n"
            "Generate a comprehensive packing list for this trip."
        )
        return await self.execute(prompt)
