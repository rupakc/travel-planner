import asyncio
import math
import re

from ..schemas.request import TravelSearchRequest
from ..services.walking_tours import fetch_city_tours, split_city_country
from .base_agent import BaseAgent
from .loader import load_agent_definition

_MAX_PER_CITY = 8
_MAX_TOP_PICKS = 2
_MIN_PER_CITY = 4
_MAX_REASON_CHARS = 200
_URL_RE = re.compile(r"https?://|www\.", re.I)


def _one_line(text: object) -> str:
    """Collapse whitespace/newlines and '|' so crawled text can't forge lines."""
    return re.sub(r"[\s|]+", " ", str(text or "")).strip()


def _clean_reason(reason: object) -> str | None:
    if not isinstance(reason, str):
        return None
    text = reason.strip()
    if not text or _URL_RE.search(text):
        return None
    return text[:_MAX_REASON_CHARS].rstrip()


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
                    _one_line(t.get("name")),
                    _one_line(t.get("provider")),
                    str(t.get("rating") if t.get("rating") is not None else "n/a"),
                    str(
                        t.get("review_count")
                        if t.get("review_count") is not None
                        else "n/a"
                    ),
                    _one_line(t.get("duration")) or "n/a",
                    _one_line(t.get("description"))[:200],
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
        top = rec.get("top_pick") is True and tops.get(city, 0) < _MAX_TOP_PICKS
        if top:
            tops[city] = tops.get(city, 0) + 1
        out.append(
            {
                **tour,
                "reason": _clean_reason(rec.get("reason")),
                "top_pick": top,
            }
        )
    return out


def top_up(tours: list[dict], picked: list[dict]) -> list[dict]:
    """Fill each city up to min(4, available) from its rating-ranked tours."""
    have = {t["id"] for t in picked}
    cities = list(dict.fromkeys(t["city"] for t in tours))
    out = list(picked)
    for city in cities:
        city_tours = [t for t in tours if t["city"] == city]
        need = min(_MIN_PER_CITY, len(city_tours)) - sum(
            1 for t in picked if t["city"] == city
        )
        for t in rank_fallback(city_tours):
            if need <= 0:
                break
            if t["id"] not in have:
                have.add(t["id"])
                out.append(t)
                need -= 1
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
        picked = merge_recommendations(tours, llm)
        results = top_up(tours, picked) if picked else rank_fallback(tours)
        return {"results": results, "sources": sources}
