import asyncio
import logging

from ..schemas.request import TravelSearchRequest
from ..utils.geo import optimize_city_order
from .base_agent import _MAX_RETRIES, BaseAgent, _get_client
from .loader import load_agent_definition

# Haiku generates at ~150 tokens/s vs Sonnet's ~37 tokens/s.
# With the concise prompt schema (no notes/duration_hours), an 11-day multi-city
# itinerary uses ~2500-3500 tokens — well within Haiku's 8192 output limit.
# This cuts generation time from ~100s to ~20-25s.
_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 8192  # Haiku ceiling — leave headroom with concise output rules below

logger = logging.getLogger(__name__)


class ChatItineraryAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "chat-itinerary"))

    async def execute(self, prompt: str) -> dict:
        """Override: use Sonnet with 16k token budget instead of Haiku."""
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                client = _get_client()
                system = (
                    self.definition.system_prompt
                    + "\n\nReturn ONLY valid JSON. No prose, no markdown fences, no tool calls."
                    "\nCONCISENESS IS CRITICAL — the JSON must fit within the output token limit:"
                    "\n- Every string value ≤ 10 words (activity, place, why, highlight, tip, cuisine)"
                    "\n- Omit the 'tip' field on morning/afternoon/evening slots entirely"
                    "\n- places_to_see: exactly 2 entries per day, 'why' ≤ 6 words"
                    "\n- dining: exactly 2 entries per day"
                    "\n- intercity_travel options: exactly 2 per leg"
                    "\n- hotel 'highlight': ≤ 8 words"
                )
                response = await client.messages.create(
                    model=_MODEL,
                    max_tokens=_MAX_TOKENS,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                result_text = response.content[0].text if response.content else ""
                logger.info(
                    f"ChatItineraryAgent raw response: {len(result_text)} chars, "
                    f"stop_reason={response.stop_reason}"
                )
                if response.stop_reason == "max_tokens":
                    logger.warning(
                        "ChatItineraryAgent hit max_tokens — JSON will be truncated. "
                        f"Response was {len(result_text)} chars. Attempting parse anyway."
                    )
            except Exception as e:
                logger.error(
                    f"ChatItineraryAgent API call failed (attempt {attempt}): {e}"
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(0.5)
                    continue
                return {"error": str(e)}

            parsed = self._parse_json(result_text)
            if parsed:
                days = parsed.get("days", [])
                logger.info(
                    f"ChatItineraryAgent parsed OK: {len(days)} days, "
                    f"total_cost=${parsed.get('total_estimated_cost_usd', '?')}"
                )
                return parsed
            logger.warning(
                f"ChatItineraryAgent JSON parse failed (attempt {attempt}), "
                f"first 200 chars: {result_text[:200]!r}"
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(0.5)

        return {"error": f"No parseable result after {_MAX_RETRIES} attempts"}

    async def run(
        self,
        request: TravelSearchRequest,
        destinations: list[str] | None = None,
        hotel_hint: str | None = None,
    ) -> dict:
        is_multi = bool(destinations and len(destinations) > 1)
        logger.info(
            f"ChatItineraryAgent.run(): destination={request.destination!r}, "
            f"destinations={destinations}, multi={is_multi}, "
            f"dates={request.departure_date}→{request.return_date}"
        )
        nights = (
            (request.return_date - request.departure_date).days
            if request.return_date
            else 7
        )
        interests_str = (
            ", ".join(request.interests) if request.interests else "general travel"
        )

        if is_multi:
            optimized = optimize_city_order(destinations, lock_first=True)
            n = len(optimized)
            base = max(2, nights // n)
            extra = nights - base * n
            city_nights = [base] * n
            for i in range(extra):
                city_nights[(n // 2 + i) % n] += 1

            city_lines = []
            current_day = 1
            for city, cn in zip(optimized, city_nights):
                end_day = current_day + cn - 1
                city_lines.append(
                    f"  {city}: Days {current_day}–{end_day} ({cn} nights)"
                )
                current_day += cn + 1

            total_days = nights + (n - 1)
            prompt = (
                f"Build a COMPREHENSIVE {total_days}-day multi-city travel plan.\n"
                f"Origin: {request.origin}\n"
                f"Dates: {request.departure_date} → {request.return_date}\n"
                f"Travelers: {request.num_travelers}\n"
                f"Interests: {interests_str}\n"
                + (
                    f"Budget: ${request.budget_usd}/person\n"
                    if request.budget_usd
                    else ""
                )
                + "\nCITY PLAN (TSP-optimized order — follow exactly):\n"
                + "\n".join(city_lines)
                + "\n\nMANDATORY RULES:\n"
                "1. Follow city order and day ranges EXACTLY.\n"
                "2. Set city + country on EVERY day.\n"
                "3. Insert one TRAVEL DAY between each city pair (is_travel_day: true).\n"
                "4. Include hotel on the FIRST day of each city's stay only.\n"
                "5. Include 2–3 places_to_see and 2 dining entries per non-travel day.\n"
                "6. Add lat/lng for every named slot and place.\n"
                "7. Include intercity_travel with 2–3 transport options per leg.\n"
                "8. Use YOUR OWN KNOWLEDGE for all recommendations.\n"
                "9. Keep activity descriptions under 20 words.\n"
            )
        else:
            prompt = (
                f"Build a COMPREHENSIVE {nights + 1}-day travel plan for {request.destination}.\n"
                f"Origin: {request.origin}\n"
                f"Dates: {request.departure_date} → {request.return_date} ({nights} nights)\n"
                f"Travelers: {request.num_travelers}\n"
                f"Interests: {interests_str}\n"
                + (
                    f"Budget: ${request.budget_usd}/person\n"
                    if request.budget_usd
                    else ""
                )
                + "\nMANDATORY RULES:\n"
                "1. Day 1: arrival, check-in, gentle intro. Last day: departure.\n"
                "2. Include hotel on Day 1 only.\n"
                "3. Include 2–3 places_to_see and 2 dining entries per non-travel day.\n"
                "4. Add lat/lng for every named slot and place.\n"
                "5. intercity_travel should have one entry: origin → destination (flight or train).\n"
                "6. Keep activity descriptions under 20 words.\n"
            )

        return await self.execute(prompt)
