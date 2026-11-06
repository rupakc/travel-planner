"""Near me: the nearest known place to a coordinate, then either

- v1 (no ``sections``; the installed Android app): the existing activities
  agent for it — same item shape as /api/activities, cached per ~5 km cell;
- v2 (``sections: true``): one Gemini call grounded with Google Maps around
  the coordinate — places to see / eat / shop / stay, each with its Google
  Maps link (services/nearby_grounded.py). Never cached: Google's Maps
  grounding terms allow results only for the user who asked."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints, model_validator

from ...agents.activities_agent import ActivitiesAgent
from ...core import llm
from ...core.auth import get_current_user
from ...core.config import settings
from ...core.places import fold_place
from ...db.places_db import nearest_place
from ...db.preferences_db import get_preferences
from ...db.taste_db import derive_taste_context
from ...schemas.request import TravelSearchRequest
from ...services import nearby_grounded

router = APIRouter()

V1_DEFAULT_LIMIT = 8
V2_DEFAULT_LIMIT = 6
V2_MAX_LIMIT = 10
CELL_DEGREES = 0.05  # ~5 km: one cache entry per cell
# Per (cell, place, interests, taste): an hour, longer than the shared
# 30-minute search cache — what's near a spot changes slowly
_cache: TTLCache = TTLCache(maxsize=settings.cache_maxsize, ttl=3600)


class NearbyRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    interests: (
        list[
            Annotated[
                str,
                StringConstraints(strip_whitespace=True, min_length=1, max_length=60),
            ]
        ]
        | None
    ) = Field(None, max_length=20)
    # v1: 1..20, default 8; v2: per section, 1..10, default 6
    limit: int | None = Field(None, ge=1, le=20)
    sections: bool = False
    language: (
        Annotated[
            str,
            StringConstraints(
                min_length=2,
                max_length=35,
                pattern=r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8}){0,3}$",
            ),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def _v2_limit(self):
        if self.sections and self.limit is not None and self.limit > V2_MAX_LIMIT:
            raise ValueError(f"limit must be at most {V2_MAX_LIMIT} per section")
        return self


def _cell(value: float) -> str:
    return f"{round(value / CELL_DEGREES) * CELL_DEGREES:.2f}"


def _label(place: dict) -> str:
    """ "Portland, Maine, United States": the region tells same-named towns
    apart; left out when it only repeats the name ("Kyoto, Japan")."""
    parts = [place["name"]]
    region = place.get("region")
    if region and fold_place(region) != fold_place(place["name"]):
        parts.append(region)
    return ", ".join([*parts, place["country"]])


def _agent_error() -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={
            "code": "agent_error",
            "message": "We couldn't find things to do nearby. Try again.",
        },
    )


async def _sections(body: NearbyRequest, place: dict, user: dict) -> dict:
    """v2. One Maps-grounded call for all four sections, not one per
    section: every Maps query the model issues is billed past the free tier,
    and our estimate is ~8 queries for one combined prompt against ~12 for
    four calls (plus 4x the prompt tokens and 4x the latency risk). Matching
    the model's ``GROUP|name|why`` lines to grounding chunk titles keeps one
    call reliable: a name without a chunk is simply dropped. Nothing is
    cached or stored (Maps grounding terms)."""
    limit = body.limit or V2_DEFAULT_LIMIT
    interests = (
        body.interests or get_preferences(user["username"]).get("interests") or []
    )
    system, prompt = nearby_grounded.build_prompt(
        _label(place),
        body.lat,
        body.lng,
        limit,
        interests,
        today=datetime.now(UTC).date().isoformat(),
    )
    try:
        out = await llm.generate_grounded(
            prompt,
            tool="maps",
            system=system,
            lat=body.lat,
            lng=body.lng,
            language=body.language or "en",
            label="nearby_maps",
        )
    except llm.LLMError as e:
        if e.user_facing:
            raise HTTPException(
                status_code=503, detail={"code": e.user_code, "message": str(e)}
            ) from e
        raise _agent_error() from e
    sections, sources = nearby_grounded.parse_sections(out.text, out.chunks, limit)
    return {
        "place": place,
        "sections": sections,
        "attribution": "Google Maps",
        "sources": sources,
    }


@router.post("/nearby")
async def nearby(body: NearbyRequest, user: dict = Depends(get_current_user)):
    place = nearest_place(body.lat, body.lng)
    if place is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "no_place",
                "message": "We don't know a town or city near you yet.",
            },
        )
    if body.sections:
        return await _sections(body, place, user)
    prefs = get_preferences(user["username"])
    interests = body.interests or prefs.get("interests") or []
    taste = derive_taste_context(user["username"])
    key = (
        "nearby",
        _cell(body.lat),
        _cell(body.lng),
        place["name"],
        place["country_code"],
        tuple(sorted({i.strip().lower() for i in interests if i.strip()})),
        taste,
    )
    items = _cache.get(key)
    if items is None:
        label = _label(place)
        today = datetime.now(UTC).date()
        request = TravelSearchRequest(
            origin=label,
            destination=label,
            departure_date=today,
            return_date=today + timedelta(days=1),
            interests=interests,
            nationality=prefs.get("nationality") or "",
        )
        request.taste_context = taste
        agent = ActivitiesAgent(agents_dir=settings.agents_dir)
        result = await agent.run(request)
        if paused := llm.user_error(result):
            raise HTTPException(
                status_code=503,
                detail={"code": paused["error_code"], "message": paused["error"]},
            )
        if result.get("error") or not isinstance(result.get("results"), list):
            raise _agent_error()
        items = result["results"]
        _cache[key] = items
    return {
        "place": place,
        "items": items[: body.limit or V1_DEFAULT_LIMIT],
    }
