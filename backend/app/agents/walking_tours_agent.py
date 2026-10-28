import asyncio
import math

from ..schemas.request import TravelSearchRequest
from ..services.walking_tours import fetch_city_tours, split_city_country
from .base_agent import BaseAgent
from .loader import load_agent_definition

_MAX_PER_CITY = 8
_MAX_TOP_PICKS = 2


def build_prompt(
    request: TravelSearchRequest, cities: list[str], tours: list[dict]
) -> str:
    """Prompt asking the LLM to pick from the crawled candidates by id."""
    interests = ", ".join(request.interests) if request.interests else "general travel"
    labels = []
    for city in cities:
        name, country = split_city_country(city)
        labels.append(
            f"{name}, {country}" if country else f"{name} (identify the country)"
        )
    lines = [
        f"Choose the best free walking tours in {' → '.join(labels)}.",
        f"Traveler interests: {interests}",
        f"Travelers: {request.traveler_context}",
    ]
    if request.serendipity_context:
        lines.append(request.serendipity_context)
    if len(cities) > 1:
        lines.append("MANDATORY COVERAGE: 4–6 tours per city — never skip a city.")
    lines += [
        "Pick 4–8 tours per city, best first, at most 2 with top_pick true "
        "per city. Each reason is at most 20 words and tied to this traveler.",
        "Never output URLs; refer to tours only by their id.",
        "",
        "Candidates (id | name | provider | rating | reviews | duration | description):",
    ]
    for t in tours:
        lines.append(
            " | ".join(
                [
                    t["id"],
                    str(t.get("name") or ""),
                    str(t.get("provider") or ""),
                    str(t.get("rating") if t.get("rating") is not None else "n/a"),
                    str(
                        t.get("review_count")
                        if t.get("review_count") is not None
                        else "n/a"
                    ),
                    str(t.get("duration") or "n/a"),
                    (t.get("description") or "")[:200],
                ]
            )
        )
    return "\n".join(lines)


def _score(tour: dict) -> float:
    rating, reviews = tour.get("rating"), tour.get("review_count")
    if rating is None or reviews is None:
        return -1.0
    return rating * math.log1p(reviews)


def rank_fallback(tours: list[dict]) -> list[dict]:
    """Rating-ranked top tours per city, without LLM annotations."""
    by_city: dict[str, list[dict]] = {}
    for t in tours:
        by_city.setdefault(t["city"], []).append(t)
    out = []
    for group in by_city.values():
        group.sort(key=_score, reverse=True)
        for t in group[:_MAX_PER_CITY]:
            out.append({**t, "reason": None, "top_pick": False})
    return out


def merge_recommendations(tours: list[dict], llm: dict) -> list[dict]:
    """Apply LLM picks to crawled tours; only ids/reason/top_pick are trusted."""
    recs = llm.get("recommendations") if isinstance(llm, dict) else None
    if not isinstance(recs, list):
        return []
    known = {t["id"]: t for t in tours}
    seen: set[str] = set()
    counts: dict[str, int] = {}
    tops: dict[str, int] = {}
    out = []
    for rec in recs:
        tour_id = rec.get("id") if isinstance(rec, dict) else None
        if not isinstance(tour_id, str) or tour_id not in known or tour_id in seen:
            continue
        seen.add(tour_id)
        tour = known[tour_id]
        city = tour["city"]
        if counts.get(city, 0) >= _MAX_PER_CITY:
            continue
        counts[city] = counts.get(city, 0) + 1
        reason = rec.get("reason")
        top = rec.get("top_pick") is True and tops.get(city, 0) < _MAX_TOP_PICKS
        if top:
            tops[city] = tops.get(city, 0) + 1
        out.append(
            {
                **tour,
                "reason": reason.strip()
                if isinstance(reason, str) and reason.strip()
                else None,
                "top_pick": top,
            }
        )
    return out


class WalkingToursAgent(BaseAgent):
    """Crawls free-walking-tour sites and has the LLM pick the best fits."""

    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "walking_tours"))

    async def run(self, request: TravelSearchRequest) -> dict:
        destinations = (
            request.destinations if request.is_multi_city else [request.destination]
        )
        crawls = await asyncio.gather(
            *(fetch_city_tours(split_city_country(d)[0]) for d in destinations)
        )
        tours = [t for city_tours, _ in crawls for t in city_tours]
        sources = [s for _, city_sources in crawls for s in city_sources]

        if sources and all(s["status"] == "error" for s in sources):
            return {"error": "Couldn't reach the walking-tour sites right now"}
        if not tours:
            return {"results": [], "sources": sources}

        llm = await self.execute(build_prompt(request, destinations, tours))
        results = merge_recommendations(tours, llm) or rank_fallback(tours)
        return {"results": results, "sources": sources}
