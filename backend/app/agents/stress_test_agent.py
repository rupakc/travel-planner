import json
from datetime import date

from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition


class StressTestAgent(BaseAgent):
    """Adversarial reviewer that audits the assembled plan for realistic problems."""

    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "stress_test"))

    async def run(
        self,
        request: TravelSearchRequest,
        itinerary: dict | None = None,
        flights: dict | None = None,
        visa: dict | None = None,
        weather: dict | None = None,
    ) -> dict:
        if not itinerary or not itinerary.get("days"):
            return {"error": "No itinerary available to stress-test"}

        prompt = self.build_prompt(request, itinerary, flights, visa, weather)
        return await self.execute(prompt)

    # ------------------------------------------------------------------
    @staticmethod
    def build_prompt(
        request: TravelSearchRequest,
        itinerary: dict,
        flights: dict | None,
        visa: dict | None,
        weather: dict | None,
    ) -> str:
        days_out = (request.departure_date - date.today()).days
        dest = (
            " → ".join(request.destinations)
            if request.destinations and len(request.destinations) > 1
            else request.destination
        )
        lines = [
            f"Trip: {request.origin} to {dest}",
            f"Dates: {request.departure_date} ({request.departure_date.strftime('%A')})"
            + (
                f" to {request.return_date} ({request.return_date.strftime('%A')})"
                if request.return_date
                else " (one-way)"
            ),
            f"Departure is {days_out} days from today ({date.today()}).",
            f"Travelers: {request.traveler_context}",
            f"Nationality: {request.nationality}",
        ]
        if request.budget_usd:
            lines.append(f"Stated budget: ${request.budget_usd:.0f} USD total")

        lines.append(StressTestAgent._summarize_itinerary(itinerary, request))

        flight_summary = StressTestAgent._summarize_flights(flights)
        if flight_summary:
            lines.append(flight_summary)

        visa_summary = StressTestAgent._summarize_visa(visa)
        if visa_summary:
            lines.append(visa_summary)

        weather_summary = StressTestAgent._summarize_weather(weather)
        if weather_summary:
            lines.append(weather_summary)

        lines.append(
            "\nAudit this plan. Find what will realistically go wrong and return "
            "the JSON verdict."
        )
        return "\n".join(lines)

    @staticmethod
    def _summarize_itinerary(itinerary: dict, request: TravelSearchRequest) -> str:
        day_lines = []
        for day in (itinerary.get("days") or [])[:16]:
            slots = []
            for slot in day.get("slots") or []:
                activity = slot.get("activity") or "?"
                dur = slot.get("duration_hours")
                cost = slot.get("estimated_cost_usd")
                bits = [f"{slot.get('time_of_day', '?')}: {activity}"]
                if slot.get("location"):
                    bits.append(f"@ {slot['location']}")
                if dur:
                    bits.append(f"{dur}h")
                if cost is not None:
                    bits.append(f"${cost}")
                slots.append(" ".join(str(b) for b in bits))
            date_str = day.get("date") or ""
            weekday = ""
            try:
                weekday = f" {date.fromisoformat(date_str).strftime('%A')}"
            except (ValueError, TypeError):
                pass
            city = f" [{day['city']}]" if day.get("city") else ""
            day_lines.append(
                f"Day {day.get('day_number')}{city} ({date_str}{weekday}): "
                + "; ".join(slots)
            )
        total = itinerary.get("total_estimated_cost_usd")
        header = "\nItinerary:"
        if total is not None:
            travelers = max(request.num_travelers, 1)
            header = (
                f"\nItinerary (estimated ${total} per person, {travelers} traveler(s)):"
            )
        return header + "\n" + "\n".join(day_lines)

    @staticmethod
    def _summarize_flights(flights: dict | None) -> str:
        results = (flights or {}).get("results") or []
        if not results:
            return ""
        f = results[0]
        parts = ["\nCheapest flight option:"]
        out = f.get("outbound") or {}
        if out:
            parts.append(
                f"Outbound {out.get('airline', '?')} departs "
                f"{out.get('departure_date', '?')} {out.get('departure_time', '?')}, "
                f"arrives {out.get('arrival_time', '?')}, stops: {out.get('stops', '?')}"
            )
        ret = f.get("return") or {}
        if ret:
            parts.append(
                f"Return {ret.get('airline', '?')} departs "
                f"{ret.get('departure_date', '?')} {ret.get('departure_time', '?')}, "
                f"arrives {ret.get('arrival_time', '?')}, stops: {ret.get('stops', '?')}"
            )
        if f.get("price_usd") is not None:
            parts.append(f"Price: ${f['price_usd']} per person")
        return "\n".join(parts)

    @staticmethod
    def _summarize_visa(visa: dict | None) -> str:
        req = (visa or {}).get("requirement")
        if not req:
            return ""
        if isinstance(req, dict):
            compact = {
                k: v
                for k, v in req.items()
                if k
                in (
                    "visa_type",
                    "visa_required",
                    "processing_time",
                    "processing_time_days",
                    "max_stay_days",
                    "notes",
                    "summary",
                )
                and v is not None
            }
            return "\nVisa requirement: " + json.dumps(compact) if compact else ""
        return f"\nVisa requirement: {req}"

    @staticmethod
    def _summarize_weather(weather: dict | None) -> str:
        days = (weather or {}).get("days") or []
        poor = [
            f"{d.get('date')} ({d.get('description')})"
            for d in days
            if d.get("is_poor")
        ]
        if not poor:
            return ""
        return "\nForecast poor-weather days: " + ", ".join(poor[:8])
