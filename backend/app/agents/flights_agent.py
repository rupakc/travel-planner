import logging
from urllib.parse import urlparse

from ..schemas.request import TravelSearchRequest
from .base_agent import ToolAgent, _URLSearchMixin
from .loader import load_agent_definition

logger = logging.getLogger(__name__)


def _url_to_source(url: str) -> str:
    _KNOWN = {
        "google.com": "google_flights",
        "skyscanner.com": "skyscanner",
        "kayak.com": "kayak",
        "expedia.com": "expedia",
        "momondo.com": "momondo",
    }
    try:
        host = urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return "web"
    for domain, name in _KNOWN.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host or "web"


class FlightsAgent(ToolAgent, _URLSearchMixin):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "flights"))

    async def run(
        self, request: TravelSearchRequest, filters: dict | None = None
    ) -> dict:
        is_round_trip = request.return_date is not None
        trip_type = "round-trip" if is_round_trip else "one-way"

        prompt = (
            f"Search for {trip_type} flights from {request.origin} to {request.destination}.\n"
            f"IMPORTANT: Identify the country for both origin and destination and include it in all results (e.g. 'Tokyo, Japan', 'Paris, France').\n"
            f"Departure date: {request.departure_date}\n"
        )
        if is_round_trip:
            prompt += f"Return date: {request.return_date}\n"
        else:
            prompt += "Return date: N/A (one-way)\n"

        prompt += (
            f"Number of travelers: {request.num_travelers}\n"
            f"Budget: {'$' + str(int(request.budget_usd)) + ' total' if request.budget_usd else 'flexible'}\n"
        )

        if is_round_trip:
            prompt += (
                f"\nIMPORTANT: Search for ROUND-TRIP flights. Each result must include "
                f"both an outbound leg ({request.origin} → {request.destination} on {request.departure_date}) "
                f"and a return leg ({request.destination} → {request.origin} on {request.return_date}). "
                f"The price_usd should be the TOTAL round-trip price per person.\n"
                f"Find 8-12 round-trip options sorted by total price."
            )
        else:
            prompt += "Find 8-12 one-way flight options sorted by price."

        if filters:
            lines = ["\n\n--- MANDATORY FLIGHT FILTERS (strictly enforce these) ---"]
            if filters.get("max_stops") is not None:
                stops = filters["max_stops"]
                if stops == 0:
                    lines.append(
                        "STOPS: Non-stop/direct flights ONLY. Do NOT include any flights with stops."
                    )
                else:
                    lines.append(
                        f"STOPS: Maximum {stops} stop(s). Exclude flights with more than {stops} stop(s)."
                    )
            if filters.get("max_price_usd") is not None:
                lines.append(
                    f"PRICE: Maximum ${int(filters['max_price_usd'])} per person. Exclude flights above this price."
                )
            dep_e = filters.get("departure_time_earliest")
            dep_l = filters.get("departure_time_latest")
            if dep_e or dep_l:
                lines.append(
                    f"DEPARTURE TIME: Only flights departing between {dep_e or '00:00'} and {dep_l or '23:59'}."
                )
            arr_e = filters.get("arrival_time_earliest")
            arr_l = filters.get("arrival_time_latest")
            if arr_e or arr_l:
                lines.append(
                    f"ARRIVAL TIME: Only flights arriving between {arr_e or '00:00'} and {arr_l or '23:59'}."
                )
            lines.append("--- END FILTERS ---")
            prompt += "\n".join(lines)

        self._origin = request.origin
        self._destination = request.destination
        return await self.execute(prompt)

    async def _enrich_urls(self, data: dict) -> dict:
        flights = data.get("results", [])
        if not flights:
            return data

        seen_airlines = set()
        for flight in flights:
            airline = flight.get("airline") or (flight.get("outbound", {}) or {}).get(
                "airline", ""
            )
            if not airline or airline in seen_airlines:
                continue
            seen_airlines.add(airline)

            # Try route-specific search first
            url = await self._search_url(
                f"{airline} flights {self._origin} to {self._destination} book",
                match_name=airline,
            )

            # Fallback: just find the airline's booking page
            if not url:
                url = await self._search_url(
                    f"{airline} airline book flights official site",
                    match_name=airline,
                )

            if url:
                source = _url_to_source(url)
                for f in flights:
                    f_airline = f.get("airline") or (f.get("outbound", {}) or {}).get(
                        "airline", ""
                    )
                    if f_airline == airline:
                        f["booking_url"] = url
                        f["source"] = source
                logger.info(f"Flight URL: {airline} -> {url} (source: {source})")

        return data
