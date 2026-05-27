"""
Pure knowledge-based planning engine for the chat interface.

Generates all travel plan sections (flights, hotels, activities, visa, SIM,
tips, getting_around, forex) in parallel from Claude's internal knowledge.

No external APIs. No search agents. No fallbacks.

To add a new section:
    Add one SectionConfig entry to SECTION_CONFIGS — nothing else changes.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from ..schemas.request import TravelSearchRequest
from .base_agent import _get_client

logger = logging.getLogger(__name__)

_KNOWLEDGE_MODEL = "claude-haiku-4-5-20251001"
_SECTION_TIMEOUT = 20.0  # per-section, seconds


# ── Planning context ──────────────────────────────────────────────────────────


@dataclass
class PlanningContext:
    """Derived context for prompt building — computed once, shared across all sections."""

    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    nights: int
    num_travelers: int
    interests: str
    nationality: str
    budget_usd: float | None
    destinations: list[str] | None

    @classmethod
    def from_request(cls, req: TravelSearchRequest) -> "PlanningContext":
        nights = (req.return_date - req.departure_date).days if req.return_date else 7
        return cls(
            origin=req.origin or "your city",
            destination=req.destination,
            departure_date=req.departure_date.isoformat(),
            return_date=req.return_date.isoformat() if req.return_date else None,
            nights=nights,
            num_travelers=req.num_travelers or 1,
            interests=", ".join(req.interests) if req.interests else "general travel",
            nationality=req.nationality or "not specified",
            budget_usd=req.budget_usd,
            destinations=req.destinations,
        )

    @property
    def return_clause(self) -> str:
        return f", returning {self.return_date}" if self.return_date else " (one-way)"

    @property
    def city_route(self) -> str:
        if self.destinations and len(self.destinations) > 1:
            return " → ".join(self.destinations)
        return self.destination

    @property
    def nationality_currency(self) -> str:
        _MAP = {
            "indian": "INR",
            "american": "USD",
            "british": "GBP",
            "australian": "AUD",
            "canadian": "CAD",
            "chinese": "CNY",
            "japanese": "JPY",
            "korean": "KRW",
            "brazilian": "BRL",
            "mexican": "MXN",
            "russian": "RUB",
            "south african": "ZAR",
            "singaporean": "SGD",
            "emirati": "AED",
            "swiss": "CHF",
            "norwegian": "NOK",
            "swedish": "SEK",
            "danish": "DKK",
        }
        return _MAP.get(self.nationality.lower(), "USD")


# ── Section configuration ─────────────────────────────────────────────────────


@dataclass
class SectionConfig:
    """All you need to define a new knowledge-generated section."""

    prompt: str
    system: str = "You are a travel expert. Return ONLY valid JSON — no prose, no markdown fences."
    max_tokens: int = 1500
    model: str = _KNOWLEDGE_MODEL


SECTION_CONFIGS: dict[str, SectionConfig] = {
    "flights": SectionConfig(
        max_tokens=1200,
        prompt=(
            "Generate 5-6 realistic flight options from {origin} to {destination}, "
            "departing {departure_date}{return_clause} for {num_travelers} traveler(s). "
            "Include budget carriers and at least one premium option. Use real airline names.\n"
            "Return JSON:\n"
            '{{"results": [{{"airline": str, "origin": str, "destination": str, '
            '"price_usd": float, "stops": int, "duration_minutes": int, '
            '"departure_time": "HH:MM", "arrival_time": "HH:MM"}}]}}'
        ),
    ),
    "hotels": SectionConfig(
        max_tokens=1500,
        prompt=(
            "Generate 6-8 realistic hotel options in {destination} for {nights} nights. "
            "Cover all tiers: budget (~$60/n), mid-range (~$120-180/n), premium (~$250-350/n), luxury (~$450+/n). "
            "Use real hotel names. Include neighbourhoods.\n"
            "Return JSON:\n"
            '{{"results": [{{"name": str, "star_rating": float, "price_per_night_usd": float, '
            '"location": str, "tier": "budget"|"mid-range"|"premium"|"luxury", '
            '"review_score": float, "amenities": [str]}}]}}'
        ),
    ),
    "activities": SectionConfig(
        max_tokens=2000,
        prompt=(
            "Generate 10-12 activities in {destination} for interests: {interests}. "
            "Mix iconic sights, local experiences, and hidden gems. "
            "Score 0.0-1.0 for interest match (1.0 = perfect match).\n"
            "Return JSON:\n"
            '{{"results": [{{"name": str, "description": str, "category": str, '
            '"duration_hours": float, "price_usd": float, "location": str, '
            '"similarity_score": float}}]}}'
        ),
    ),
    "visa": SectionConfig(
        max_tokens=600,
        prompt=(
            "Visa requirements for a {nationality} passport holder visiting {destination}. "
            "Be accurate; note this is general guidance only.\n"
            "Return JSON:\n"
            '{{"requirement": {{"visa_type": str, "max_stay_days": int, '
            '"requirements": [str], "processing_time": str, "fee_usd": float, '
            '"confidence": "knowledge-based", "notes": str}}}}'
        ),
    ),
    "sim": SectionConfig(
        max_tokens=1200,
        prompt=(
            "SIM card and eSIM options for travelers in {destination}. "
            "Include local SIM, tourist SIM, and at least one eSIM option. Use real provider names. "
            "Return exactly 4 options.\n"
            "Return JSON:\n"
            '{{"plans": [{{"provider": str, "plan_name": str, "data_gb": float, '
            '"validity_days": int, "price_usd": float, "purchase_location": str, '
            '"network_quality": {{"speed": str, "coverage_rating": "excellent"|"good"|"moderate"}}}}]}}'
        ),
    ),
    "tips": SectionConfig(
        max_tokens=1500,
        prompt=(
            "Give 8-10 essential travel tips for {destination} for a {nationality} traveler. "
            "Cover: safety, cultural norms, common scams, transport, tipping, food, and practical hacks.\n"
            "Return JSON:\n"
            '{{"tips": [{{"category": str, "title": str, "body": str, '
            '"severity": "info"|"warning"|"danger"}}]}}'
        ),
    ),
    "getting_around": SectionConfig(
        max_tokens=1200,
        prompt=(
            "5-7 transportation options for tourists in {destination}. "
            "Cover metro, bus, taxi/rideshare, bike, and unique local options.\n"
            "Return JSON:\n"
            '{{"options": [{{"name": str, "type": str, "scope": "intra_city"|"inter_city", '
            '"description": str, "price_info": str, "tips": str}}]}}'
        ),
    ),
    "forex": SectionConfig(
        max_tokens=1000,
        prompt=(
            "Currency and money info for travelers in {destination}. "
            "Include exchange rates from USD, EUR, and {nationality_currency}.\n"
            "Return JSON:\n"
            '{{"local_currency": {{"name": str, "code": str, "symbol": str}}, '
            '"exchange_rates": [{{"from_currency": str, "to_currency": str, "rate": float, "description": str}}], '
            '"cash_advice": {{"cash_dependency": "high"|"medium"|"low", "recommendation": str}}, '
            '"tipping": {{"expected": bool, "description": str}}, '
            '"money_tips": [{{"title": str, "body": str}}]}}'
        ),
    ),
}


# ── Engine ────────────────────────────────────────────────────────────────────


class KnowledgePlanningEngine:
    """
    Generates every travel section from Claude's internal knowledge.

    All sections run in parallel. Each call to run_all() yields
    (section_name, result_dict) as each section completes.

    Adding a section: add one SectionConfig entry to SECTION_CONFIGS.
    """

    def __init__(self, configs: dict[str, SectionConfig] | None = None):
        self.configs = configs or SECTION_CONFIGS

    async def generate_section(self, section: str, ctx: PlanningContext) -> dict:
        """Generate one section. Always returns a dict (never raises)."""
        cfg = self.configs.get(section)
        if not cfg:
            return {"error": f"unknown section: {section}"}

        try:
            prompt = cfg.prompt.format(
                origin=ctx.origin,
                destination=ctx.destination,
                departure_date=ctx.departure_date,
                return_clause=ctx.return_clause,
                nights=ctx.nights,
                num_travelers=ctx.num_travelers,
                interests=ctx.interests,
                nationality=ctx.nationality,
                city_route=ctx.city_route,
                nationality_currency=ctx.nationality_currency,
                budget_usd=ctx.budget_usd or "not specified",
            )
        except KeyError as e:
            return {"error": f"prompt build error: {e}"}

        try:
            client = _get_client()
            response = await client.messages.create(
                model=cfg.model,
                max_tokens=cfg.max_tokens,
                system=cfg.system,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text if response.content else ""
            parsed = self._parse_json(text)
            if parsed:
                parsed["knowledge_estimate"] = True
                logger.info(f"KnowledgePlanner [{section}]: OK ({len(text)} chars)")
                return parsed
            logger.warning(
                f"KnowledgePlanner [{section}]: parse failed — {text[:120]!r}"
            )
            return {"error": "JSON parse failed", "knowledge_estimate": True}
        except Exception as e:
            logger.error(f"KnowledgePlanner [{section}]: {e}")
            return {"error": str(e), "knowledge_estimate": True}

    async def run_all(
        self, request: TravelSearchRequest, sections: list[str] | None = None
    ):
        """
        Async generator — yields (name, data) as each section completes.

        Usage:
            async for section, data in engine.run_all(request):
                ...
        """
        target = sections if sections is not None else list(self.configs.keys())
        ctx = PlanningContext.from_request(request)
        done: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

        async def _run(name: str) -> None:
            try:
                result = await asyncio.wait_for(
                    self.generate_section(name, ctx), timeout=_SECTION_TIMEOUT
                )
            except TimeoutError:
                logger.warning(f"KnowledgePlanner [{name}]: timed out")
                result = {"error": "timeout", "knowledge_estimate": True}
            await done.put((name, result))

        tasks = [asyncio.create_task(_run(s)) for s in target]
        for _ in tasks:
            yield await done.get()

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        for fn in [
            lambda: json.loads(text.strip()),
            lambda: json.loads(
                re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
                .group(1)
                .strip()
            ),
            lambda: json.loads(re.search(r"\{.*\}", text, re.DOTALL).group(0)),
        ]:
            try:
                r = fn()
                if isinstance(r, dict):
                    return r
            except (json.JSONDecodeError, AttributeError):
                continue
        return None
