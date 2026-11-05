"""Near me (Android app): the nearest known place to a coordinate, then the
existing activities agent for it — same item shape as /api/activities."""

from datetime import UTC, datetime, timedelta

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...agents.activities_agent import ActivitiesAgent
from ...core.auth import get_current_user
from ...core.config import settings
from ...db.places_db import nearest_place
from ...db.preferences_db import get_preferences
from ...db.taste_db import derive_taste_context
from ...schemas.request import TravelSearchRequest

router = APIRouter()

CELL_DEGREES = 0.05  # ~5 km: one cache entry per cell
# Per (cell, place, interests, taste): an hour, longer than the shared
# 30-minute search cache — what's near a spot changes slowly
_cache: TTLCache = TTLCache(maxsize=settings.cache_maxsize, ttl=3600)


class NearbyRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    interests: list[str] | None = Field(None, max_length=20)
    limit: int = Field(8, ge=1, le=20)


def _cell(value: float) -> str:
    return f"{round(value / CELL_DEGREES) * CELL_DEGREES:.2f}"


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
        label = f"{place['name']}, {place['country']}"
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
        if result.get("error") or not isinstance(result.get("results"), list):
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "agent_error",
                    "message": "We couldn't find things to do nearby. Try again.",
                },
            )
        items = result["results"]
        _cache[key] = items
    return {
        "place": place,
        "items": items[: body.limit],
    }
