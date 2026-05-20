import asyncio
import logging
from datetime import timedelta

from ..schemas.request import TravelSearchRequest
from .activities_agent import ActivitiesAgent
from .flights_agent import FlightsAgent
from .forex_agent import ForexAgent
from .getting_around_agent import GettingAroundAgent
from .hotels_agent import HotelsAgent
from .itinerary_agent import ItineraryAgent
from .places_agent import PlacesAgent
from .sim_agent import SimAgent
from .tips_agent import TipsAgent
from .visa_agent import VisaAgent

logger = logging.getLogger(__name__)


class TravelOrchestrator:
    def __init__(self, agents_dir: str):
        self.flights = FlightsAgent(agents_dir)
        self.hotels = HotelsAgent(agents_dir)
        self.activities = ActivitiesAgent(agents_dir)
        self.visa = VisaAgent(agents_dir)
        self.sim = SimAgent(agents_dir)
        self.tips = TipsAgent(agents_dir)
        self.getting_around = GettingAroundAgent(agents_dir)
        self.forex = ForexAgent(agents_dir)
        self.places = PlacesAgent(agents_dir)
        self.itinerary = ItineraryAgent(agents_dir)

    async def run(self, request: TravelSearchRequest) -> dict:
        """Run all agents: Phase 1 in parallel, Phase 2 sequential."""
        logger.info(
            f"Starting travel planning for {request.origin} -> {request.destination}"
        )

        # Phase 1: Run all independent agents in parallel
        phase1_results = await asyncio.gather(
            self.flights.run(request),
            self.hotels.run(request),
            self.activities.run(request),
            self.visa.run(request),
            self.sim.run(request),
            self.tips.run(request),
            self.getting_around.run(request),
            self.forex.run(request),
            self.places.run(request),
            return_exceptions=True,
        )

        def safe(result, fallback):
            if isinstance(result, Exception):
                logger.error(f"Agent failed: {result}")
                return {"error": str(result)}
            return result or fallback

        flights = safe(phase1_results[0], {"results": []})
        hotels = safe(phase1_results[1], {"results": []})
        activities = safe(phase1_results[2], {"results": []})
        visa = safe(phase1_results[3], {"requirement": None})
        sim = safe(phase1_results[4], {"plans": []})
        tips = safe(phase1_results[5], {"tips": []})
        getting_around = safe(phase1_results[6], {"options": []})
        forex = safe(phase1_results[7], {"exchange_rates": []})
        places_to_see = safe(phase1_results[8], {"results": []})

        # Phase 2: Itinerary uses activities + hotels
        itinerary = await self.itinerary.run(
            request, activities=activities, hotels=hotels
        )

        return {
            "flights": flights,
            "hotels": hotels,
            "activities": activities,
            "places_to_see": places_to_see,
            "visa": visa,
            "sim": sim,
            "tips": tips,
            "getting_around": getting_around,
            "forex": forex,
            "itinerary": itinerary,
        }

    async def stream_run(self, request: TravelSearchRequest):
        """Stream results with a static-first, AI-enhanced pattern.

        Phase 0 (instant, < 1s):
            Yield static/pre-computed results for visa, SIM, and tips from
            Python lookup tables.  These appear on the UI immediately.

        Phase 1 (parallel AI agents):
            Launch all 7 specialist agents concurrently.  As each completes,
            yield its result.  For visa/sim/tips this replaces the static
            version.  Itinerary starts as soon as activities + hotels arrive.

        Phase 2 (itinerary):
            Wait for the itinerary agent with keepalive pings; fall back to
            the template builder after 60 s.
        """
        import json

        from .static_results import (
            get_static_forex,
            get_static_getting_around,
            get_static_sim,
            get_static_tips,
            get_static_visa,
        )

        # ── Phase 0: Instant static results ──────────────────────────────
        static_visa = get_static_visa(request)
        static_sim = get_static_sim(request)
        static_tips = get_static_tips(request)
        static_getting_around = get_static_getting_around(request)
        static_forex = get_static_forex(request)

        if static_visa:
            yield f"data: {json.dumps({'type': 'visa', 'data': static_visa, 'source': 'static'})}\n\n"
        if static_sim:
            yield f"data: {json.dumps({'type': 'sim', 'data': static_sim, 'source': 'static'})}\n\n"
        if static_tips:
            yield f"data: {json.dumps({'type': 'tips', 'data': static_tips, 'source': 'static'})}\n\n"
        if static_getting_around:
            yield f"data: {json.dumps({'type': 'getting_around', 'data': static_getting_around, 'source': 'static'})}\n\n"
        if static_forex:
            yield f"data: {json.dumps({'type': 'forex', 'data': static_forex, 'source': 'static'})}\n\n"

        logger.info("Static results yielded for visa/sim/tips/getting_around/forex")

        # Notify frontend that AI agents are starting
        for name in [
            "flights",
            "hotels",
            "activities",
            "places_to_see",
            "visa",
            "sim",
            "tips",
            "getting_around",
            "forex",
        ]:
            yield f"data: {json.dumps({'type': 'agent_status', 'agent': name, 'status': 'searching'})}\n\n"

        # ── Phase 1: Parallel AI agents (fast — no web searches) ────────
        results = {}
        queue: asyncio.Queue = asyncio.Queue()
        itinerary_task = None

        async def run_agent(name: str, coro):
            try:
                result = await coro
            except Exception as e:
                logger.error(f"Agent {name} failed: {e}")
                result = {"error": str(e)}
            await queue.put((name, result))

        phase1_agents = {
            "flights": self.flights,
            "hotels": self.hotels,
            "activities": self.activities,
            "places_to_see": self.places,
            "visa": self.visa,
            "sim": self.sim,
            "tips": self.tips,
            "getting_around": self.getting_around,
            "forex": self.forex,
        }

        phase1_tasks = [
            asyncio.create_task(run_agent(name, agent.run(request)))
            for name, agent in phase1_agents.items()
        ]

        _STATIC_BACKED = {"visa", "sim", "tips", "getting_around", "forex"}

        # Enrichment starts per-agent as soon as each Phase 1 result arrives
        enrich_queue: asyncio.Queue = asyncio.Queue()
        enrich_tasks = []

        async def enrich_agent(name: str, agent, data: dict):
            import copy

            try:
                if hasattr(agent, "enrich"):
                    data_copy = copy.deepcopy(data)
                    enriched = await agent.enrich(data_copy)
                    await enrich_queue.put((name, enriched))
                else:
                    await enrich_queue.put((name, None))
            except Exception as e:
                logger.warning(f"URL enrichment failed for {name}: {e}")
                await enrich_queue.put((name, None))

        for _ in range(len(phase1_tasks)):
            name, result = await queue.get()
            results[name] = result

            if name in _STATIC_BACKED and result.get("error"):
                logger.info(f"Agent {name} errored, retaining Phase 0 static data")
            else:
                yield f"data: {json.dumps({'type': name, 'data': result, 'source': 'ai'})}\n\n"

            # Start enrichment immediately for this agent
            if not result.get("error"):
                agent = phase1_agents.get(name)
                if agent:
                    enrich_tasks.append(
                        asyncio.create_task(enrich_agent(name, agent, result))
                    )

            if (
                itinerary_task is None
                and "activities" in results
                and "hotels" in results
            ):
                logger.info("Starting itinerary agent (activities+hotels ready)")
                itinerary_task = asyncio.create_task(
                    self.itinerary.run(
                        request,
                        activities=results["activities"],
                        hotels=results["hotels"],
                    )
                )

        # ── Phase 2: Drain remaining enrichments + itinerary ─────────────
        if itinerary_task is None:
            itinerary_task = asyncio.create_task(
                self.itinerary.run(
                    request,
                    activities=results.get("activities", {}),
                    hotels=results.get("hotels", {}),
                )
            )

        enriched_count = 0
        itinerary_done = False
        itinerary_timeout = 60
        timer_start = asyncio.get_event_loop().time()

        while enriched_count < len(enrich_tasks) or not itinerary_done:
            now = asyncio.get_event_loop().time()
            if not itinerary_done and (now - timer_start) > itinerary_timeout:
                itinerary_task.cancel()
                logger.warning("Itinerary agent timed out after %ds", itinerary_timeout)
                itinerary = self._build_fallback_itinerary(
                    request, results.get("activities", {}), results.get("hotels", {})
                )
                yield f"data: {json.dumps({'type': 'itinerary', 'data': itinerary})}\n\n"
                itinerary_done = True
                continue

            if not itinerary_done and itinerary_task.done():
                try:
                    itinerary = itinerary_task.result()
                    if not itinerary or not itinerary.get("days"):
                        raise ValueError("Empty itinerary result")
                except Exception as e:
                    logger.warning(
                        f"Itinerary agent returned bad result ({e}), using fallback"
                    )
                    itinerary = self._build_fallback_itinerary(
                        request,
                        results.get("activities", {}),
                        results.get("hotels", {}),
                    )
                yield f"data: {json.dumps({'type': 'itinerary', 'data': itinerary})}\n\n"
                itinerary_done = True
                continue

            try:
                name, enriched = await asyncio.wait_for(enrich_queue.get(), timeout=3)
                enriched_count += 1
                if enriched is not None:
                    yield f"data: {json.dumps({'type': name, 'data': enriched, 'source': 'ai'})}\n\n"
                    logger.info(f"Streamed enriched URLs for {name}")
            except TimeoutError:
                yield ": keepalive\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    # ------------------------------------------------------------------
    def _build_fallback_itinerary(
        self,
        request: TravelSearchRequest,
        activities: dict,
        hotels: dict,
    ) -> dict:
        """Template-based itinerary — no AI call, instant, used as fallback."""
        nights = (
            (request.return_date - request.departure_date).days
            if request.return_date
            else 7
        )
        activity_list = [
            a for a in (activities.get("results") or []) if not a.get("error")
        ]
        hotel_name = (
            hotels.get("results", [{}])[0].get("name", "your hotel")
            if hotels.get("results")
            else "your hotel"
        )

        themes = [
            "Arrival & First Impressions",
            *[f"Day {i + 2} — Exploration" for i in range(max(0, nights - 2))],
            "Last Day & Departure",
        ]

        days = []
        act_idx = 0
        total_cost = 0.0

        for day_num in range(1, nights + 2):
            date_str = (
                request.departure_date + timedelta(days=day_num - 1)
            ).isoformat()
            is_first = day_num == 1
            is_last = day_num == nights + 1
            theme = themes[min(day_num - 1, len(themes) - 1)]

            slots = []
            if is_first:
                slots = [
                    {
                        "time_of_day": "morning",
                        "activity": f"Arrive at {request.destination}, transfer to {hotel_name}",
                        "location": request.destination,
                        "duration_hours": 3.0,
                        "notes": "Check transport options from the airport in advance",
                        "estimated_cost_usd": 30.0,
                    },
                    {
                        "time_of_day": "afternoon",
                        "activity": f"Check in to {hotel_name}, freshen up, explore the neighbourhood",
                        "location": request.destination,
                        "duration_hours": 3.0,
                        "notes": "Pick up a local SIM or eSIM if not done already",
                        "estimated_cost_usd": 20.0,
                    },
                    {
                        "time_of_day": "evening",
                        "activity": "Welcome dinner — try a local restaurant recommended by the hotel",
                        "location": request.destination,
                        "duration_hours": 2.0,
                        "notes": "Ask hotel staff for their favourite spots",
                        "estimated_cost_usd": 40.0,
                    },
                ]
            elif is_last:
                slots = [
                    {
                        "time_of_day": "morning",
                        "activity": "Final breakfast, last-minute souvenir shopping",
                        "location": request.destination,
                        "duration_hours": 2.0,
                        "notes": "Pack the night before",
                        "estimated_cost_usd": 30.0,
                    },
                    {
                        "time_of_day": "afternoon",
                        "activity": f"Check out of {hotel_name}, head to airport",
                        "location": request.destination,
                        "duration_hours": 3.0,
                        "notes": "Allow extra time for check-in queues",
                        "estimated_cost_usd": 30.0,
                    },
                    {
                        "time_of_day": "evening",
                        "activity": "Departure flight",
                        "location": "Airport",
                        "duration_hours": 3.0,
                        "notes": "Safe travels!",
                        "estimated_cost_usd": 0.0,
                    },
                ]
            else:
                day_slots = []
                for tod in ("morning", "afternoon", "evening"):
                    if act_idx < len(activity_list):
                        a = activity_list[act_idx]
                        act_idx += 1
                        day_slots.append(
                            {
                                "time_of_day": tod,
                                "activity": a.get("name", "Local exploration"),
                                "location": a.get("location", request.destination),
                                "duration_hours": a.get("duration_hours", 2.0),
                                "notes": a.get("description", ""),
                                "estimated_cost_usd": float(a.get("price_usd") or 25),
                            }
                        )
                    else:
                        day_slots.append(
                            {
                                "time_of_day": tod,
                                "activity": f"Free time — explore {request.destination} at your own pace",
                                "location": request.destination,
                                "duration_hours": 3.0,
                                "notes": "Great opportunity for spontaneous discoveries",
                                "estimated_cost_usd": 30.0,
                            }
                        )
                slots = day_slots

            daily_cost = sum(s["estimated_cost_usd"] for s in slots)
            total_cost += daily_cost
            days.append(
                {
                    "day_number": day_num,
                    "date": date_str,
                    "theme": theme,
                    "slots": slots,
                    "daily_estimated_cost_usd": daily_cost,
                }
            )

        return {"days": days, "total_estimated_cost_usd": round(total_cost, 2)}
