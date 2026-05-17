import json
import asyncio
import re
import logging
from datetime import date, timedelta
from .base_agent import _get_client, _MODEL
from .loader import load_agent_definition
from .flights_agent import FlightsAgent
from .hotels_agent import HotelsAgent
from .activities_agent import ActivitiesAgent
from .visa_agent import VisaAgent
from .sim_agent import SimAgent
from .tips_agent import TipsAgent
from .getting_around_agent import GettingAroundAgent
from .forex_agent import ForexAgent
from .itinerary_agent import ItineraryAgent
from ..schemas.request import TravelSearchRequest

_CHAT_MODEL = "claude-sonnet-4-6"

logger = logging.getLogger(__name__)

_PLANNING_PATTERNS = re.compile(
    r'|'.join([
        r'\bitinerar',
        r'\bplan\b.{0,30}\b(trip|travel|vacation|holiday|getaway)',
        r'\b(trip|travel|vacation|holiday)\b.{0,30}\bplan',
        r'\bbook\b.{0,30}\b(everything|flights?\b.{0,15}hotels?|hotels?\b.{0,15}flights?)',
        r'\bfull\b.{0,20}\b(trip|travel)\b.{0,15}\bplan',
        r'\borganize\b.{0,20}\b(trip|travel|vacation)',
        r'\bplan\b.{0,15}\bfor\s+me\b',
        r'\bsearch\b.{0,20}\b(flights?\b.{0,15}hotels?|everything)',
        r'\bwhat\s+do\s+i\s+need\b.{0,30}\b(trip|travel|visit)',
        r'\bhelp\s+me\s+(plan|organize|book)\b',
    ]),
    re.IGNORECASE,
)

_INTENT_MAP = {
    'flights': re.compile(r'\b(flight|fly|airline|airport|ticket|depart|arrive|airfare|plane)\b', re.I),
    'hotels': re.compile(r'\b(hotel|stay|accommodation|hostel|airbnb|resort|lodge|booking|room)\b', re.I),
    'activities': re.compile(r'\b(activit|thing.{0,10}to do|sightse|tour|museum|excursion|attraction|experience|visit)\b', re.I),
    'visa': re.compile(r'\b(visa|passport|entry.{0,10}require|immigration|permit|travel.{0,10}document)\b', re.I),
    'sim': re.compile(r'\b(sim|esim|phone|data.{0,10}plan|mobile|connectivity|internet)\b', re.I),
    'tips': re.compile(r'\b(tip|safety|scam|danger|advice|warn|culture|customs|etiquette)\b', re.I),
    'getting_around': re.compile(r'\b(transport|metro|subway|bus|taxi|uber|getting around|train|tram|commut)\b', re.I),
    'forex': re.compile(r'\b(forex|currency|exchange\s+rate|money\s+exchange|atm|cash|local\s+money|convert|conversion)\b', re.I),
}

_PLAN_PATTERNS = re.compile(
    r'|'.join([
        r'\b(add|put|include|save)\b.{0,30}\b(plan|my plan|the plan)',
        r'\b(remove|delete|drop|take out|take off)\b.{0,30}\b(plan|my plan|the plan|from.{0,10}plan)',
        r'\b(remove|delete|drop|take out|take off)\b.{0,30}\b(flight|hotel|sim|activit|tip|transport)',
        r'\b(change|swap|replace|switch|update)\b.{0,30}\b(flight|hotel|sim|activit)',
        r'\b(change|swap|replace|switch|update)\b.{0,30}\b(plan|my plan|the plan)',
        r'\bclear\b.{0,15}\b(plan|my plan|the plan|everything)',
        r"\bwhat.{0,10}(in|on).{0,10}(plan|my plan)",
        r"\bshow\b.{0,10}\b(plan|my plan)",
        r"\bmy plan\b",
        r"\bthe plan\b",
    ]),
    re.IGNORECASE,
)

_BUDGET_MAP = {"low": 1000, "medium": 3000, "high": 8000}

_ALL_AGENT_NAMES = ["flights", "hotels", "activities", "visa", "sim", "tips", "getting_around", "forex"]


class ChatAgent:
    def __init__(self, agents_dir: str):
        self.agents_dir = agents_dir
        self.definition = load_agent_definition(agents_dir, "chat")

    @staticmethod
    def _classify_intent(message: str) -> list[str]:
        matched = [name for name, pattern in _INTENT_MAP.items() if pattern.search(message)]
        return matched

    async def stream(
        self,
        messages: list[dict],
        preferences: dict | None = None,
        selections: dict | None = None,
        search_results: dict | None = None,
    ):
        """Stream chat responses with plan management.

        Routing:
        1. Plan commands (add/remove/change/show/clear) -> handle plan + respond
        2. Planning patterns -> run all agents + auto-build plan
        3. Specific intent -> run matched agents + add relevant items to plan
        4. Regular chat
        """
        last_msg = messages[-1]["content"] if messages else ""
        selections = selections or {}
        search_results = search_results or {}

        # 1. Check for plan manipulation commands
        if _PLAN_PATTERNS.search(last_msg):
            has_search_context = bool(search_results)
            needs_agents = self._classify_intent(last_msg)

            if needs_agents and not has_search_context:
                params = await self._extract_travel_params(messages, preferences)
                if params:
                    async for chunk in self._run_comprehensive_planning(
                        params, messages, preferences, selections,
                        agent_names=needs_agents,
                    ):
                        yield chunk
                    return

            async for chunk in self._handle_plan_command(
                messages, preferences, selections, search_results,
            ):
                yield chunk
            return

        # 2. Full trip planning
        if _PLANNING_PATTERNS.search(last_msg):
            params = await self._extract_travel_params(messages, preferences)
            if params:
                async for chunk in self._run_comprehensive_planning(
                    params, messages, preferences, selections,
                ):
                    yield chunk
                return

        # 3. Specific intent agents
        matched_agents = self._classify_intent(last_msg)
        if matched_agents:
            params = await self._extract_travel_params(messages, preferences)
            if params:
                async for chunk in self._run_comprehensive_planning(
                    params, messages, preferences, selections,
                    agent_names=matched_agents,
                ):
                    yield chunk
                return

        # 4. Regular chat (plan-aware)
        async for chunk in self._regular_chat(messages, preferences, selections):
            yield chunk

    # ── Plan command handling ─────────────────────────────────────────

    async def _handle_plan_command(
        self,
        messages: list[dict],
        preferences: dict | None,
        selections: dict,
        search_results: dict,
    ):
        """Use LLM to interpret a plan command and emit plan_action events."""
        last_msg = messages[-1]["content"]

        plan_summary = self._summarize_selections(selections)
        results_summary = self._summarize_search_results(search_results)

        prompt = (
            "The user wants to modify their travel plan. Analyze their request and return a JSON response.\n\n"
            f"User message: \"{last_msg}\"\n\n"
            f"Current plan contents:\n{plan_summary}\n\n"
            f"Available search results:\n{results_summary}\n\n"
            "Return a JSON object with:\n"
            "- \"actions\": list of plan actions, each with:\n"
            "  - \"action\": \"set\" | \"add\" | \"remove\" | \"clear\"\n"
            "  - \"field\": \"flight\" | \"hotel\" | \"sim\" | \"activities\" | \"tips\" | \"getting_around\" | \"itinerary_slots\" | \"all\"\n"
            "  - \"data\": the item data (for set/add), or {\"name\": \"...\"} / {\"title\": \"...\"} for remove, or null for clear\n"
            "- \"message\": a friendly confirmation message to show the user (1-2 sentences, use markdown)\n\n"
            "For 'show'/'what's in my plan' requests, return empty actions and summarize the plan in the message.\n"
            "For 'clear' requests, use action='clear' with field='all'.\n"
            "For 'remove' with a specific type (e.g., 'remove the flight'), use action='clear' with the field name.\n"
            "For 'add' requests, pick the best matching item from search results.\n"
            "For 'change/swap' requests, use action='set' with the new item from search results.\n"
            "If the user asks to add something not in search results, return actions=[] and explain in the message.\n"
            "IMPORTANT: Return ONLY valid JSON."
        )

        try:
            client = _get_client()
            response = await client.messages.create(
                model=_MODEL,
                max_tokens=4096,
                system="You manage a travel plan. Return only valid JSON with actions and a message.",
                messages=[{"role": "user", "content": prompt}],
            )
            result_text = response.content[0].text if response.content else ""
            parsed = self._parse_json_text(result_text)

            if parsed:
                actions = parsed.get("actions", [])
                message = parsed.get("message", "Done!")

                for action in actions:
                    yield json.dumps({"type": "plan_action", **action})

                yield json.dumps({"type": "delta", "text": message})
                yield json.dumps({"type": "done"})
                return
        except Exception as e:
            logger.warning(f"Plan command handling failed: {e}")

        async for chunk in self._regular_chat(messages, preferences, selections):
            yield chunk

    # ── Auto-build plan from results ──────────────────────────────────

    @staticmethod
    def _auto_build_plan(results: dict) -> list[dict]:
        """Programmatically pick the best items from agent results for the plan."""
        actions = []

        # Best flight: cheapest
        flights = results.get("flights", {}).get("results", [])
        if flights:
            valid = [f for f in flights if not f.get("error")]
            if valid:
                cheapest = min(valid, key=lambda f: f.get("price_usd") or f.get("total_price_usd") or 99999)
                actions.append({"action": "set", "field": "flight", "data": cheapest})

        # Best hotel: mid-range, highest rated
        hotels = results.get("hotels", {}).get("results", [])
        if hotels:
            valid = [h for h in hotels if not h.get("error")]
            if valid:
                mid = [h for h in valid if h.get("tier") in ("mid-range", "premium")]
                pool = mid if mid else valid
                best = max(pool, key=lambda h: h.get("rating", 0))
                actions.append({"action": "set", "field": "hotel", "data": best})

        # Top 5 activities by similarity score
        activities = results.get("activities", {}).get("results", [])
        if activities:
            valid = [a for a in activities if not a.get("error")]
            top = sorted(valid, key=lambda a: a.get("similarity_score", 0), reverse=True)[:5]
            for activity in top:
                actions.append({"action": "add", "field": "activities", "data": activity})

        # Best SIM: best coverage at reasonable price
        sims = results.get("sim", {}).get("plans", results.get("sim", {}).get("results", []))
        if sims:
            valid = [s for s in sims if not s.get("error")]
            if valid:
                def sim_score(s):
                    rating_map = {"excellent": 4, "good": 3, "moderate": 2, "limited": 1}
                    nq = s.get("network_quality", {})
                    coverage = rating_map.get(nq.get("coverage_rating", ""), 0)
                    price = s.get("price_usd", 999)
                    return (coverage * 10) - price
                best_sim = max(valid, key=sim_score)
                actions.append({"action": "set", "field": "sim", "data": best_sim})

        # Top tips: danger and warning severity
        tips = results.get("tips", {}).get("tips", results.get("tips", {}).get("results", []))
        if tips:
            important = [t for t in tips if t.get("severity") in ("danger", "warning")]
            for tip in important[:5]:
                actions.append({"action": "add", "field": "tips", "data": tip})

        # Top 3 transport options
        transport = results.get("getting_around", {}).get("options", results.get("getting_around", {}).get("results", []))
        if transport:
            for opt in transport[:3]:
                actions.append({"action": "add", "field": "getting_around", "data": opt})

        # Itinerary slots
        itinerary = results.get("itinerary", {})
        if itinerary.get("days"):
            for day in itinerary["days"]:
                for slot in day.get("slots", []):
                    key = f"{day['day_number']}-{slot['time_of_day']}"
                    actions.append({"action": "add", "field": "itinerary_slots", "data": {
                        "key": key,
                        "day_number": day["day_number"],
                        "time_of_day": slot["time_of_day"],
                        "activity": slot.get("activity", ""),
                        "location": slot.get("location", ""),
                        "estimated_cost_usd": slot.get("estimated_cost_usd", 0),
                    }})

        return actions

    # ── Helpers for plan context ──────────────────────────────────────

    @staticmethod
    def _summarize_selections(selections: dict) -> str:
        if not selections or all(
            not v for k, v in selections.items()
            if k not in ("itinerary_notes", "itinerary_edits")
        ):
            return "Plan is empty — no items selected yet."

        lines = []
        if selections.get("flight"):
            f = selections["flight"]
            lines.append(f"- Flight: {f.get('airline', 'Unknown')} — ${f.get('price_usd', '?')}")
        if selections.get("hotel"):
            h = selections["hotel"]
            lines.append(f"- Hotel: {h.get('name', 'Unknown')} — ${h.get('price_per_night_usd', '?')}/night")
        if selections.get("activities"):
            for a in selections["activities"]:
                lines.append(f"- Activity: {a.get('name', 'Unknown')} — ${a.get('price_usd', '?')}")
        if selections.get("sim"):
            s = selections["sim"]
            lines.append(f"- SIM: {s.get('provider', 'Unknown')} {s.get('plan_name', '')} — ${s.get('price_usd', '?')}")
        if selections.get("tips"):
            for t in selections["tips"]:
                lines.append(f"- Tip: {t.get('title', 'Unknown')}")
        if selections.get("getting_around"):
            for g in selections["getting_around"]:
                lines.append(f"- Transport: {g.get('name', 'Unknown')}")
        if selections.get("itinerary_slots"):
            lines.append(f"- Itinerary: {len(selections['itinerary_slots'])} slots selected")
        return "\n".join(lines) if lines else "Plan is empty."

    @staticmethod
    def _summarize_search_results(results: dict) -> str:
        if not results:
            return "No search results available."

        lines = []
        if results.get("flights", {}).get("results"):
            flights = results["flights"]["results"]
            lines.append(f"Flights: {len(flights)} options (${min(f.get('price_usd', 9999) for f in flights)}-${max(f.get('price_usd', 0) for f in flights)})")
        if results.get("hotels", {}).get("results"):
            hotels = results["hotels"]["results"]
            lines.append(f"Hotels: {len(hotels)} options")
        if results.get("activities", {}).get("results"):
            acts = results["activities"]["results"]
            lines.append(f"Activities: {len(acts)} options")
            for a in acts[:5]:
                lines.append(f"  - {a.get('name', '?')} (${a.get('price_usd', '?')})")
        if results.get("sim", {}).get("plans"):
            sims = results["sim"]["plans"]
            lines.append(f"SIM cards: {len(sims)} options")
            for s in sims[:3]:
                lines.append(f"  - {s.get('provider', '?')} {s.get('plan_name', '')} (${s.get('price_usd', '?')})")
        if results.get("tips", {}).get("tips"):
            lines.append(f"Tips: {len(results['tips']['tips'])} available")
        if results.get("getting_around", {}).get("options", results.get("getting_around", {}).get("results")):
            opts = results["getting_around"].get("options", results["getting_around"].get("results", []))
            lines.append(f"Transport: {len(opts)} options")
        if results.get("forex", {}).get("exchange_rates"):
            rates = results["forex"]["exchange_rates"]
            lines.append(f"Forex: {len(rates)} exchange rates, currency info available")
        return "\n".join(lines) if lines else "No search results available."

    # ── Regular chat (plan-aware) ─────────────────────────────────────

    async def _regular_chat(self, messages: list[dict], preferences: dict | None = None, selections: dict | None = None):
        system_prompt = self._build_system_prompt(preferences, selections)
        api_messages = self._to_api_messages(messages)

        try:
            client = _get_client()
            async with client.messages.stream(
                model=_CHAT_MODEL,
                max_tokens=4096,
                system=system_prompt,
                messages=api_messages,
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield json.dumps({"type": "delta", "text": text})
            yield json.dumps({"type": "done"})
        except Exception as e:
            logger.error(f"Chat agent error: {e}")
            yield json.dumps({"type": "error", "text": str(e)})

    # ── Comprehensive planning ────────────────────────────────────────

    async def _extract_travel_params(self, messages: list[dict], preferences: dict | None) -> TravelSearchRequest | None:
        conversation = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in messages[-6:]
        )

        pref_lines = []
        if preferences:
            if preferences.get("nationality"):
                pref_lines.append(f"nationality: {preferences['nationality']}")
            if preferences.get("current_residence"):
                pref_lines.append(f"current_residence: {preferences['current_residence']}")
            if preferences.get("budget_category"):
                pref_lines.append(f"budget_usd: {_BUDGET_MAP.get(preferences['budget_category'], 3000)}")
            if preferences.get("residence_permits"):
                pref_lines.append(f"residence_permits: {json.dumps(preferences['residence_permits'])}")
            if preferences.get("existing_visas"):
                pref_lines.append(f"existing_visas: {json.dumps(preferences['existing_visas'])}")
            if preferences.get("interests"):
                pref_lines.append(f"interests: {json.dumps(preferences['interests'])}")
            if preferences.get("num_travelers", 1) > 1:
                pref_lines.append(f"num_travelers: {preferences['num_travelers']}")
        pref_block = ("\n\nUser's saved preferences:\n" + "\n".join(pref_lines)) if pref_lines else ""

        extraction_prompt = (
            "Extract travel planning parameters from this conversation. Return ONLY a JSON object.\n"
            'If there is NOT enough info to plan (need at minimum: destination), return {"insufficient": true}.\n\n'
            f"Conversation:\n{conversation}\n{pref_block}\n\n"
            "Return JSON with fields: origin (string), destination (string), "
            "departure_date (YYYY-MM-DD), return_date (YYYY-MM-DD or null), "
            "interests (list), nationality (string), residence_permits (list), "
            "existing_visas (list), budget_usd (number or null), num_travelers (int).\n"
            f"Use preferences to fill missing fields. Today is {date.today().isoformat()}. "
            "Convert relative dates (\"next week\", \"in June\") to actual dates.\n"
            "IMPORTANT for origin: If the user has not specified an origin/departure city, "
            "use their current_residence from preferences. If current_residence is also empty, "
            "use the capital city of their nationality's country. Never leave origin empty if "
            "nationality or current_residence is available."
        )

        try:
            client = _get_client()
            response = await client.messages.create(
                model=_MODEL,
                max_tokens=1024,
                system="You extract travel parameters into JSON. Return only valid JSON, no explanation.",
                messages=[{"role": "user", "content": extraction_prompt}],
            )
            result_text = response.content[0].text if response.content else ""

            params = self._parse_json_text(result_text)
            if not params or params.get("insufficient") or not params.get("destination"):
                return None

            dep_date = self._safe_date(params.get("departure_date"), fallback=date.today() + timedelta(days=14))
            ret_date = self._safe_date(params.get("return_date"), fallback=dep_date + timedelta(days=7))

            return TravelSearchRequest(
                origin=params.get("origin") or "",
                destination=params["destination"],
                departure_date=dep_date,
                return_date=ret_date,
                interests=params.get("interests") or [],
                nationality=params.get("nationality") or "not specified",
                residence_permits=params.get("residence_permits") or [],
                existing_visas=params.get("existing_visas") or [],
                budget_usd=params.get("budget_usd"),
                num_travelers=params.get("num_travelers") or 1,
            )
        except Exception as e:
            logger.warning(f"Travel param extraction failed: {e}")
            return None

    async def _run_comprehensive_planning(
        self,
        request: TravelSearchRequest,
        messages: list[dict],
        preferences: dict | None,
        selections: dict | None = None,
        agent_names: list[str] | None = None,
    ):
        from .static_results import get_static_visa, get_static_sim, get_static_tips, get_static_getting_around, get_static_forex

        run_all = agent_names is None
        active_agents = _ALL_AGENT_NAMES if run_all else agent_names

        yield json.dumps({"type": "planning_start", "destination": request.destination})

        # Phase 0: Instant static results
        _STATIC_GETTERS = {
            "visa": get_static_visa,
            "sim": get_static_sim,
            "tips": get_static_tips,
            "getting_around": get_static_getting_around,
            "forex": get_static_forex,
        }

        for section_name, getter in _STATIC_GETTERS.items():
            if section_name in active_agents:
                static_data = getter(request)
                if static_data:
                    yield json.dumps({"type": "section_result", "section": section_name, "data": static_data, "source": "static"})

        # Phase 1: Run agents in parallel
        _AGENT_CLASSES = {
            "flights":       FlightsAgent,
            "hotels":        HotelsAgent,
            "activities":    ActivitiesAgent,
            "visa":          VisaAgent,
            "sim":           SimAgent,
            "tips":          TipsAgent,
            "getting_around": GettingAroundAgent,
            "forex":         ForexAgent,
        }

        agents = {
            name: cls(self.agents_dir)
            for name, cls in _AGENT_CLASSES.items()
            if name in active_agents
        }

        results = {}
        done_queue: asyncio.Queue = asyncio.Queue()
        itinerary_task = None

        async def _run(name, coro):
            try:
                result = await coro
            except Exception as e:
                logger.error(f"Agent {name} failed: {e}")
                result = {"error": str(e)}
            await done_queue.put((name, result))

        tasks = [
            asyncio.create_task(_run(name, agent.run(request)))
            for name, agent in agents.items()
        ]

        _STATIC_BACKED = {"visa", "sim", "tips", "getting_around", "forex"}
        run_itinerary = run_all or ("activities" in active_agents and "hotels" in active_agents)

        for _ in range(len(tasks)):
            name, result = await done_queue.get()
            results[name] = result

            if name in _STATIC_BACKED and result.get("error"):
                logger.info(f"Agent {name} errored, retaining Phase 0 static data")
            else:
                yield json.dumps({"type": "section_result", "section": name, "data": result, "source": "ai"})

            if run_itinerary and itinerary_task is None and "activities" in results and "hotels" in results:
                itinerary_task = asyncio.create_task(
                    ItineraryAgent(self.agents_dir).run(
                        request, activities=results["activities"], hotels=results["hotels"],
                    )
                )

        # Phase 2: Itinerary
        if run_itinerary:
            if itinerary_task is None:
                itinerary_task = asyncio.create_task(
                    ItineraryAgent(self.agents_dir).run(
                        request, activities=results.get("activities", {}), hotels=results.get("hotels", {}),
                    )
                )
            try:
                results["itinerary"] = await asyncio.wait_for(itinerary_task, timeout=60)
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning(f"Itinerary agent issue: {e}")
                results["itinerary"] = {"error": str(e)}

            yield json.dumps({"type": "section_result", "section": "itinerary", "data": results["itinerary"], "source": "ai"})

        # Phase 3: Auto-build plan from results
        if run_all:
            plan_actions = self._auto_build_plan(results)
            if plan_actions:
                yield json.dumps({"type": "plan_clear"})
                for action in plan_actions:
                    yield json.dumps({"type": "plan_action", **action})
                yield json.dumps({"type": "plan_ready"})
                logger.info(f"Auto-built plan with {len(plan_actions)} items")

        yield json.dumps({"type": "planning_done"})

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_json_text(text: str) -> dict | None:
        if not text:
            return None
        for attempt in [
            lambda: json.loads(text.strip()),
            lambda: json.loads(re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL).group(1).strip()),
            lambda: json.loads(re.search(r'\{.*\}', text, re.DOTALL).group(0)),
        ]:
            try:
                return attempt()
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    @staticmethod
    def _safe_date(val, fallback: date) -> date:
        if not val:
            return fallback
        try:
            return date.fromisoformat(val)
        except (ValueError, TypeError):
            return fallback

    def _build_system_prompt(self, preferences: dict | None, selections: dict | None = None) -> str:
        base = self.definition.system_prompt
        parts = []

        # Plan state
        if selections:
            plan_summary = self._summarize_selections(selections)
            parts.append(f"\n\n## Current My Plan\n{plan_summary}")

        if not preferences:
            return base + "\n".join(parts) if parts else base

        has_nationality = bool(preferences.get("nationality"))
        has_residence = bool(preferences.get("current_residence"))
        has_budget = bool(preferences.get("budget_category"))
        has_permits = bool(preferences.get("residence_permits"))
        has_visas = bool(preferences.get("existing_visas"))
        has_interests = bool(preferences.get("interests"))
        has_travelers = preferences.get("num_travelers", 1) > 1

        filled_fields = []
        budget_labels = {"low": "Budget (~$1,000)", "medium": "Mid-range (~$3,000)", "high": "Luxury (~$8,000)"}

        parts.append("\n\n## Current User Profile\n")
        parts.append("The user has saved these preferences. **DO NOT ask about information "
                      "already provided below** — use it directly in your recommendations:\n")

        if has_nationality:
            parts.append(f"- **Nationality**: {preferences['nationality']}")
            filled_fields.append("nationality")
        if has_residence:
            parts.append(f"- **Current residence**: {preferences['current_residence']}")
            filled_fields.append("current residence")
        if has_budget:
            label = budget_labels.get(preferences["budget_category"], preferences["budget_category"])
            parts.append(f"- **Budget preference**: {label}")
            filled_fields.append("budget")
        if has_permits:
            parts.append(f"- **Residence permits**: {', '.join(preferences['residence_permits'])}")
            filled_fields.append("residence permits")
        if has_visas:
            parts.append(f"- **Existing visas**: {', '.join(preferences['existing_visas'])}")
            filled_fields.append("existing visas")
        if has_interests:
            parts.append(f"- **Interests**: {', '.join(preferences['interests'])}")
            filled_fields.append("interests")
        if has_travelers:
            parts.append(f"- **Group size**: {preferences['num_travelers']} travelers")
            filled_fields.append("number of travelers")

        if filled_fields:
            parts.append(f"\n**IMPORTANT**: Since you already know the user's {', '.join(filled_fields)}, "
                         "do NOT ask about these again. Only ask clarifying questions about details "
                         "that are NOT in the profile above.")
        else:
            parts.append("\nNo preferences are filled in yet. Ask the user for key details: "
                         "destination, dates, budget, nationality (for visa info), and interests.")

        parts.append("\n\n**CRITICAL**: Before generating a trip plan or searching for flights, you MUST "
                     "know the user's nationality and origin/departure city. If nationality is unknown, "
                     "ask for it. If no origin city is specified and no current_residence is in the profile, "
                     "ask where they will be departing from.")

        return base + "\n".join(parts)

    @staticmethod
    def _to_api_messages(messages: list[dict]) -> list[dict]:
        if not messages:
            return [{"role": "user", "content": "Hello"}]

        api_msgs = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if api_msgs and api_msgs[-1]["role"] == role:
                api_msgs[-1]["content"] += "\n\n" + content
            else:
                api_msgs.append({"role": role, "content": content})

        if api_msgs[0]["role"] != "user":
            api_msgs.insert(0, {"role": "user", "content": "(continuing conversation)"})

        return api_msgs
