import logging
import time
from urllib.parse import urlparse

from ..core.config import settings
from ..schemas.request import TravelSearchRequest
from ..services.serp_flights import SerpAPIError
from ..services.serp_flights import search as serp_search
from ..services.serp_flights import search_multi_city as serp_search_multi_city
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

    async def enrich(self, data: dict) -> dict:
        if any(r.get("source") == "google_flights" for r in data.get("results", [])):
            return data  # SerpAPI results already have authoritative booking URLs
        return await self._enrich_urls(data)

    async def run(
        self, request: TravelSearchRequest, filters: dict | None = None
    ) -> dict:
        if request.is_multi_city:
            return await self._run_multi_city(request, filters)
        if settings.serpapi_key:
            try:
                t0 = time.monotonic()
                result = await serp_search(settings.serpapi_key, request, filters)
                logger.info(
                    "SerpAPI flights: %d results in %.0fms",
                    len(result.get("results", [])),
                    (time.monotonic() - t0) * 1000,
                )
                if result.get("results"):
                    return result
                logger.info("SerpAPI returned no results, falling back to AI agent")
            except SerpAPIError as exc:
                logger.warning("SerpAPI failed (%s), falling back to AI agent", exc)

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
            f"Travelers: {request.traveler_context}\n"
            f"Budget: {'$' + str(int(request.budget_usd)) + ' total' if request.budget_usd else 'flexible'}\n"
        )
        if request.children or request.infants:
            prompt += (
                "Note: the group includes young travelers — infants (0-4) usually "
                "fly at ~10% of adult fare on laps, children (5-17) at child fare. "
                "price_usd remains the ADULT per-person fare.\n"
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

        if request.taste_context:
            prompt += (
                f"\n{request.taste_context}\n"
                "If the profile shows a flight-style preference (e.g. non-stop), "
                "rank matching options higher."
            )

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

    async def _run_multi_city(
        self, request: TravelSearchRequest, filters: dict | None = None
    ) -> dict:
        """Cover EVERY leg of a multi-city journey: origin → city1 → … → origin."""
        legs = request.flight_legs or []

        if settings.serpapi_key:
            try:
                t0 = time.monotonic()
                result = await serp_search_multi_city(
                    settings.serpapi_key, request, filters
                )
                logger.info(
                    "SerpAPI multi-city flights: %d legs, %d results in %.0fms",
                    len(result.get("legs", [])),
                    len(result.get("results", [])),
                    (time.monotonic() - t0) * 1000,
                )
                empty = [lg for lg in result.get("legs", []) if not lg.get("results")]
                if empty:
                    logger.info(
                        "Multi-city: %d legs empty after SerpAPI, AI-filling: %s",
                        len(empty),
                        [lg.get("label") for lg in empty],
                    )
                    filled = await self._ai_fill_legs(request, empty)
                    for lg in result.get("legs", []):
                        if not lg.get("results"):
                            lg["results"] = filled.get(lg.get("leg_index"), [])
                    result["results"] = [
                        f
                        for lg in result.get("legs", [])
                        for f in lg.get("results", [])
                    ]
                return result
            except SerpAPIError as exc:
                logger.warning(
                    "SerpAPI multi-city failed (%s), falling back to AI agent", exc
                )

        leg_lines = "\n".join(
            f"  Leg {i + 1}: {leg['from']} → {leg['to']} on {leg['date']} (one-way)"
            for i, leg in enumerate(legs)
        )
        prompt = (
            f"Search flights for a MULTI-CITY trip: {request.destination_label}.\n"
            f"You MUST return one-way flight options for EVERY leg below — "
            f"not just the first or last:\n{leg_lines}\n"
            f"Travelers: {request.traveler_context}\n"
            f"Budget: {'$' + str(int(request.budget_usd)) + ' total' if request.budget_usd else 'flexible'}\n"
            "Return 3-5 one-way options PER LEG sorted by price. Every result "
            "MUST include: leg_index (0-based, matching the legs above), "
            "leg_from, leg_to, leg_date, and a city field set to leg_to. "
            "price_usd is the one-way price per person for that leg. "
            "IMPORTANT: identify the country for each city and use full "
            "locations in origin/destination fields (e.g. 'Rome, Italy')."
        )
        if request.taste_context:
            prompt += (
                f"\n{request.taste_context}\n"
                "If the profile shows a flight-style preference (e.g. non-stop), "
                "rank matching options higher."
            )

        self._origin = request.origin
        self._destination = request.destination
        data = await self.execute(prompt)
        return self._group_legs(data, legs)

    async def _ai_fill_legs(
        self, request: TravelSearchRequest, empty_legs: list[dict]
    ) -> dict[int, list[dict]]:
        """AI-estimate flight options for legs SerpAPI could not serve.

        Every leg of the journey must show options — an empty NYC → Paris
        row when the intra-EU hops all resolved reads as 'multi-city is
        broken'. Returns {leg_index: [flights]}.
        """
        leg_lines = "\n".join(
            f"  Leg index {lg['leg_index']}: {lg['from']} → {lg['to']} "
            f"on {lg['date']} (one-way)"
            for lg in empty_legs
        )
        prompt = (
            "Provide realistic one-way flight options for these journey legs "
            f"(part of a multi-city trip):\n{leg_lines}\n"
            f"Travelers: {request.traveler_context}\n"
            "Return 3-5 one-way options PER LEG sorted by price. Every result "
            "MUST include: leg_index (use the exact leg index numbers above), "
            "leg_from, leg_to, leg_date, and a city field set to leg_to. "
            "price_usd is a realistic current one-way price per person. "
            "Use full 'City, Country' locations in origin/destination fields."
        )
        self._origin = request.origin
        self._destination = request.destination
        data = await self.execute(prompt)
        if "error" in data:
            logger.warning("AI leg fill failed: %s", data.get("error"))
            return {}
        valid = {lg["leg_index"]: lg for lg in empty_legs}
        out: dict[int, list[dict]] = {}
        for flight in data.get("results", []):
            try:
                idx = int(flight.get("leg_index", -1))
            except (TypeError, ValueError):
                continue
            leg = valid.get(idx)
            if not leg:
                continue
            flight.setdefault("city", leg["to"])
            flight.setdefault("leg_date", str(leg["date"]))
            flight.setdefault("leg_from", leg["from"])
            flight.setdefault("leg_to", leg["to"])
            flight.setdefault("source", "estimate")
            out.setdefault(idx, []).append(flight)
        return out

    @staticmethod
    def _group_legs(data: dict, legs: list[dict]) -> dict:
        """Group flat leg-tagged AI results into the legs structure the UI expects."""
        results = data.get("results", [])
        if "error" in data or not results:
            return data
        grouped: list[dict] = [
            {
                "leg_index": i,
                "label": f"{leg['from']} → {leg['to']}",
                "date": str(leg["date"]),
                "from": leg["from"],
                "to": leg["to"],
                "results": [],
            }
            for i, leg in enumerate(legs)
        ]
        for flight in results:
            try:
                idx = int(flight.get("leg_index", -1))
            except (TypeError, ValueError):
                idx = -1
            if 0 <= idx < len(grouped):
                flight.setdefault("city", grouped[idx]["to"])
                flight.setdefault("leg_date", grouped[idx]["date"])
                grouped[idx]["results"].append(flight)
        data["trip_type"] = "multi_city"
        data["legs"] = grouped
        # Flattened results follow the user's journey order, leg by leg
        data["results"] = [f for leg in grouped for f in leg["results"]]
        return data

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
