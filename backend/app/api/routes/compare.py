import asyncio
import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException

from ...agents.flights_agent import FlightsAgent
from ...agents.hotels_agent import HotelsAgent
from ...agents.static_results import get_confidence_score, get_static_visa
from ...agents.visa_agent import VisaAgent
from ...agents.weather_agent import WeatherAgent
from ...core.auth import get_current_user
from ...core.cache import get_cache
from ...core.config import settings
from ...schemas.request import TravelSearchRequest
from ...services.compare import summarize_destination

logger = logging.getLogger(__name__)
router = APIRouter()

_FLIGHTS_TIMEOUT = 45
_HOTELS_TIMEOUT = 45
_WEATHER_TIMEOUT = 30
_VISA_TIMEOUT = 30

# HotelsAgent and VisaAgent keep per-request fields on the instance; sharing
# them is only safe because compare never calls enrich().
_flights_agent: FlightsAgent | None = None
_hotels_agent: HotelsAgent | None = None
_weather_agent: WeatherAgent | None = None
_visa_agent: VisaAgent | None = None


def get_flights_agent() -> FlightsAgent:
    global _flights_agent
    if _flights_agent is None:
        _flights_agent = FlightsAgent(settings.agents_dir)
    return _flights_agent


def get_hotels_agent() -> HotelsAgent:
    global _hotels_agent
    if _hotels_agent is None:
        _hotels_agent = HotelsAgent(settings.agents_dir)
    return _hotels_agent


def get_weather_agent() -> WeatherAgent:
    global _weather_agent
    if _weather_agent is None:
        _weather_agent = WeatherAgent(settings.agents_dir)
    return _weather_agent


def get_visa_agent() -> VisaAgent:
    global _visa_agent
    if _visa_agent is None:
        _visa_agent = VisaAgent(settings.agents_dir)
    return _visa_agent


async def _piece(name: str, coro, timeout: float) -> dict | None:
    """Await one agent call; None on timeout, exception or an error result."""
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError:
        logger.warning("Compare %s timed out after %ss", name, timeout)
        return None
    except Exception as e:
        logger.warning("Compare %s failed: %s", name, e)
        return None
    if not isinstance(result, dict) or result.get("error"):
        logger.warning("Compare %s returned an error result", name)
        return None
    return result


@router.post("/compare/destination")
async def compare_destination(
    request: TravelSearchRequest, _user: dict = Depends(get_current_user)
):
    if request.is_multi_city:
        raise HTTPException(
            status_code=422, detail="Compare works with single destinations"
        )

    cache_key = (
        "compare:"
        + hashlib.md5(
            request.model_dump_json().encode(), usedforsecurity=False
        ).hexdigest()
    )
    cache = get_cache()
    if cached := cache.get(cache_key):
        return cached

    # Build every agent first so a failing factory can't strand coroutines.
    static_visa = get_static_visa(request)
    flights_agent = get_flights_agent()
    hotels_agent = get_hotels_agent()
    weather_agent = get_weather_agent()
    visa_agent = None if static_visa else get_visa_agent()

    visa_task = (
        visa_agent.run(request) if visa_agent else asyncio.sleep(0, result=static_visa)
    )
    flights, hotels, weather, visa = await asyncio.gather(
        _piece("flights", flights_agent.run(request), _FLIGHTS_TIMEOUT),
        _piece("hotels", hotels_agent.run(request), _HOTELS_TIMEOUT),
        _piece("weather", weather_agent.run(request), _WEATHER_TIMEOUT),
        _piece("visa", visa_task, _VISA_TIMEOUT),
    )

    if all(p is None for p in (flights, hotels, weather, visa)):
        raise HTTPException(
            status_code=502, detail="Couldn't load this destination — please retry"
        )

    summary = summarize_destination(
        request,
        flights,
        hotels,
        weather,
        visa,
        get_confidence_score(request),
        visa_verified=static_visa is not None,
    )
    if not summary["missing"]:  # only complete results are cached
        cache[cache_key] = summary
    return summary
