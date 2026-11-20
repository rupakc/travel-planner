"""Place facts agent: the ``facts`` section (docs/Place-Facts.md).

Crawler facts first (with their own sources); the model adds facts from its
own knowledge only for the groups the crawler left empty, each labelled
``origin: "ai"`` and never with a source or link. If the model fails, the
crawler facts stay; with no crawler facts the section is the model's error.
"""

from __future__ import annotations

import inspect
import logging

from ..schemas.request import TravelSearchRequest
from ..services import place_facts as pf
from .base_agent import BaseAgent, locale_kw
from .loader import load_agent_definition

logger = logging.getLogger(__name__)

_LABELS = {
    "city": "city",
    "place": "destination",
    "region": "state / region",
    "country": "country",
}


def _locale(request) -> str:
    return getattr(request, "locale", None) or "en"


async def crawler_section(request: TravelSearchRequest) -> dict:
    """The section built from the crawler alone (no model call): every place
    with its crawler facts, empty groups where it had none."""
    scopes = pf.scopes_for(request)
    crawler = await pf.crawler_facts_for(scopes, _locale(request))
    return pf.build_section(scopes, crawler)


class PlaceFactsAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "place_facts"))

    def _prompt(self, request: TravelSearchRequest, section: dict) -> str:
        holes = pf.gaps(section)
        per = pf.AI_PER_GROUP_MULTI if request.is_multi_city else pf.AI_PER_GROUP
        lines = []
        for p in section["places"]:
            missing = holes.get(p["key"])
            if not missing:
                continue
            where = p["name"]
            if p.get("country_name") and p["scope"] != "country":
                where = f"{where}, {p['country_name']}"
            lines.append(
                f'- key "{p["key"]}": {where} ({_LABELS.get(p["scope"], p["scope"])}) '
                f"— groups: {', '.join(missing)}"
            )
        prompt = (
            f"Trip: {request.destination_label}.\n"
            f"Write up to {per} facts per listed group for each place below "
            "(skip a group rather than guess).\n" + "\n".join(lines) + "\n"
        )
        return prompt + pf.reference_prompt(section)

    async def run(self, request: TravelSearchRequest, crawler=None) -> dict:
        """``crawler``: the Phase 0 section, or an awaitable of it (the
        orchestrator shares one fetch), or None to fetch it here."""
        try:
            if crawler is None:
                section = await crawler_section(request)
            elif inspect.isawaitable(crawler):
                section = await crawler
            else:
                section = crawler
        except Exception as e:  # never lose the section over the crawler
            logger.warning("place_facts crawler step failed: %s", e)
            section = pf.build_section(pf.scopes_for(request), None)
        if not section.get("places"):
            return {"error": "No place to describe", "error_code": "no_place"}
        if not pf.gaps(section):
            return pf.public(section)
        result = await self.execute(
            self._prompt(request, section), **locale_kw(request)
        )
        if not isinstance(result, dict) or result.get("error"):
            if pf.has_facts(section):
                logger.info("place_facts AI failed; keeping the crawler facts")
                return pf.public(section)
            return result if isinstance(result, dict) else {"error": "no result"}
        per = pf.AI_PER_GROUP_MULTI if request.is_multi_city else pf.AI_PER_GROUP
        merged = pf.merge_ai(section, result, per_group=per)
        if not pf.has_facts(merged):
            return {"error": "No facts found", "error_code": "no_facts"}
        return pf.public(merged)
