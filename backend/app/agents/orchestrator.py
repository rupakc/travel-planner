import asyncio
import logging
from datetime import timedelta

from ..schemas.request import TravelSearchRequest
from .activities_agent import ActivitiesAgent
from .emergency_card_agent import EmergencyCardAgent
from .events_agent import EventsAgent
from .flights_agent import FlightsAgent
from .forex_agent import ForexAgent
from .getting_around_agent import GettingAroundAgent
from .hotels_agent import HotelsAgent
from .itinerary_agent import ItineraryAgent
from .packing_list_agent import PackingListAgent
from .places_agent import PlacesAgent
from .pricing_advisor_agent import PricingAdvisorAgent
from .sim_agent import SimAgent
from .stress_test_agent import StressTestAgent
from .tips_agent import TipsAgent
from .visa_agent import VisaAgent
from .weather_agent import WeatherAgent

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
        self.weather = WeatherAgent(agents_dir)
        self.emergency_card = EmergencyCardAgent(agents_dir)
        self.events = EventsAgent(agents_dir)
        self.packing_list = PackingListAgent(agents_dir)
        self.pricing_advisor = PricingAdvisorAgent(agents_dir)
        self.stress_test = StressTestAgent(agents_dir)

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
            self.events.run(request),
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
        events = safe(phase1_results[9], {"results": []})

        # Phase 2: Itinerary uses activities + hotels
        itinerary = await self.itinerary.run(
            request,
            activities=activities,
            hotels=hotels,
            destinations=request.destinations,
        )

        # Phase 3: Stress-test audits the assembled plan
        stress_test = await self.stress_test.run(
            request, itinerary=itinerary, flights=flights, visa=visa
        )

        return {
            "stress_test": stress_test,
            "flights": flights,
            "hotels": hotels,
            "activities": activities,
            "places_to_see": places_to_see,
            "events": events,
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
            get_confidence_score,
            get_static_emergency_card,
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

        confidence = get_confidence_score(request)
        if confidence:
            yield f"data: {json.dumps({'type': 'confidence', 'data': confidence, 'source': 'static'})}\n\n"

        static_emergency = get_static_emergency_card(request)
        if static_emergency:
            yield f"data: {json.dumps({'type': 'emergency_card', 'data': static_emergency, 'source': 'static'})}\n\n"

        logger.info(
            "Static results yielded for visa/sim/tips/getting_around/forex/confidence/emergency_card"
        )

        # Notify frontend that AI agents are starting
        for name in [
            "flights",
            "weather",
            "hotels",
            "activities",
            "places_to_see",
            "events",
            "visa",
            "sim",
            "tips",
            "emergency_card",
            "getting_around",
            "forex",
            "packing_list",
            "pricing_advisor",
        ]:
            yield f"data: {json.dumps({'type': 'agent_status', 'agent': name, 'status': 'searching'})}\n\n"

        # ── Phase 1: Parallel AI agents (fast — no web searches) ────────
        results = {}
        queue: asyncio.Queue = asyncio.Queue()
        itinerary_task = None
        packing_list_task = None
        pricing_advisor_task = None
        stress_test_task = None
        stress_started_at = None

        async def run_agent(name: str, coro):
            try:
                result = await coro
            except Exception as e:
                logger.error(f"Agent {name} failed: {e}")
                result = {"error": str(e)}
            await queue.put((name, result))

        phase1_agents = {
            "flights": self.flights,
            "weather": self.weather,
            "hotels": self.hotels,
            "activities": self.activities,
            "places_to_see": self.places,
            "events": self.events,
            "visa": self.visa,
            "sim": self.sim,
            "tips": self.tips,
            "emergency_card": self.emergency_card,
            "getting_around": self.getting_around,
            "forex": self.forex,
        }

        phase1_tasks = [
            asyncio.create_task(run_agent(name, agent.run(request)))
            for name, agent in phase1_agents.items()
        ]

        _STATIC_BACKED = {
            "visa",
            "sim",
            "tips",
            "getting_around",
            "forex",
            "emergency_card",
        }

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
                        destinations=request.destinations,
                    )
                )

            # Deferred: packing_list starts when activities ready AND weather done
            if (
                packing_list_task is None
                and "activities" in results
                and (
                    "weather" in results
                    or (results.get("weather", {}) or {}).get("error")
                )
            ):
                logger.info("Starting packing_list agent")
                packing_list_task = asyncio.create_task(
                    self.packing_list.run(
                        request,
                        weather=results.get("weather"),
                        activities=results.get("activities"),
                    )
                )

            # Deferred: pricing_advisor starts when flights ready (with valid results)
            flights_result = results.get("flights", {})
            if (
                pricing_advisor_task is None
                and "flights" in results
                and not flights_result.get("error")
                and len(flights_result.get("results", [])) >= 3
            ):
                prices = [
                    f["price_usd"]
                    for f in flights_result.get("results", [])
                    if f.get("price_usd")
                ]
                avg_price = sum(prices) / len(prices) if prices else None
                logger.info("Starting pricing_advisor agent")
                pricing_advisor_task = asyncio.create_task(
                    self.pricing_advisor.run(
                        request, flights=flights_result, avg_price=avg_price
                    )
                )

        # ── Phase 2: Drain remaining enrichments + itinerary + deferred ─────────────
        if itinerary_task is None:
            itinerary_task = asyncio.create_task(
                self.itinerary.run(
                    request,
                    activities=results.get("activities", {}),
                    hotels=results.get("hotels", {}),
                    destinations=request.destinations,
                )
            )

        if packing_list_task is None:
            packing_list_task = asyncio.create_task(
                self.packing_list.run(
                    request,
                    weather=results.get("weather"),
                    activities=results.get("activities", {}),
                )
            )

        if pricing_advisor_task is None:
            prices = [
                f["price_usd"]
                for f in results.get("flights", {}).get("results", [])
                if f.get("price_usd")
            ]
            if prices:
                avg_price = sum(prices) / len(prices)
                pricing_advisor_task = asyncio.create_task(
                    self.pricing_advisor.run(
                        request,
                        flights=results.get("flights"),
                        avg_price=avg_price,
                    )
                )

        enriched_count = 0
        itinerary_done = False
        stress_done = False
        packing_done = packing_list_task is None
        pricing_done = pricing_advisor_task is None
        itinerary_timeout = 60
        deferred_timeout = 45
        stress_timeout = 45
        timer_start = asyncio.get_event_loop().time()

        def start_stress_test(itinerary_data: dict):
            nonlocal stress_test_task, stress_started_at
            stress_test_task = asyncio.create_task(
                self.stress_test.run(
                    request,
                    itinerary=itinerary_data,
                    flights=results.get("flights"),
                    visa=results.get("visa"),
                    weather=results.get("weather"),
                )
            )
            stress_started_at = asyncio.get_event_loop().time()

        while (
            enriched_count < len(enrich_tasks)
            or not itinerary_done
            or not packing_done
            or not pricing_done
            or not stress_done
        ):
            now = asyncio.get_event_loop().time()
            elapsed = now - timer_start

            if not itinerary_done and elapsed > itinerary_timeout:
                itinerary_task.cancel()
                logger.warning("Itinerary agent timed out after %ds", itinerary_timeout)
                itinerary = self._build_fallback_itinerary(
                    request, results.get("activities", {}), results.get("hotels", {})
                )
                yield f"data: {json.dumps({'type': 'itinerary', 'data': itinerary})}\n\n"
                itinerary_done = True
                yield f"data: {json.dumps({'type': 'agent_status', 'agent': 'stress_test', 'status': 'searching'})}\n\n"
                start_stress_test(itinerary)
                continue

            if not packing_done and elapsed > deferred_timeout:
                if packing_list_task:
                    packing_list_task.cancel()
                logger.warning(
                    "Packing list agent timed out after %ds", deferred_timeout
                )
                packing_done = True
                continue

            if not pricing_done and elapsed > deferred_timeout:
                if pricing_advisor_task:
                    pricing_advisor_task.cancel()
                logger.warning(
                    "Pricing advisor agent timed out after %ds", deferred_timeout
                )
                pricing_done = True
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
                yield f"data: {json.dumps({'type': 'agent_status', 'agent': 'stress_test', 'status': 'searching'})}\n\n"
                start_stress_test(itinerary)
                continue

            if not stress_done and stress_test_task and stress_test_task.done():
                try:
                    stress_result = stress_test_task.result()
                except Exception as e:
                    logger.warning(f"Stress test agent failed: {e}")
                    stress_result = {"error": str(e)}
                if not stress_result.get("error"):
                    yield f"data: {json.dumps({'type': 'stress_test', 'data': stress_result, 'source': 'ai'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'agent_status', 'agent': 'stress_test', 'status': 'done'})}\n\n"
                stress_done = True
                continue

            if (
                not stress_done
                and stress_started_at is not None
                and asyncio.get_event_loop().time() - stress_started_at > stress_timeout
            ):
                if stress_test_task:
                    stress_test_task.cancel()
                logger.warning("Stress test agent timed out after %ds", stress_timeout)
                yield f"data: {json.dumps({'type': 'agent_status', 'agent': 'stress_test', 'status': 'done'})}\n\n"
                stress_done = True
                continue

            if not packing_done and packing_list_task and packing_list_task.done():
                try:
                    packing_result = packing_list_task.result()
                except Exception as e:
                    logger.warning(f"Packing list agent failed: {e}")
                    packing_result = {"error": str(e)}
                if not packing_result.get("error"):
                    yield f"data: {json.dumps({'type': 'packing_list', 'data': packing_result, 'source': 'ai'})}\n\n"
                packing_done = True
                continue

            if (
                not pricing_done
                and pricing_advisor_task
                and pricing_advisor_task.done()
            ):
                try:
                    pricing_result = pricing_advisor_task.result()
                except Exception as e:
                    logger.warning(f"Pricing advisor agent failed: {e}")
                    pricing_result = {"error": str(e)}
                if not pricing_result.get("error"):
                    yield f"data: {json.dumps({'type': 'pricing_advisor', 'data': pricing_result, 'source': 'ai'})}\n\n"
                pricing_done = True
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
