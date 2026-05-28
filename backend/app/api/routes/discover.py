import asyncio
import hashlib
import logging

from fastapi import APIRouter, HTTPException

from ...agents.discovery_agent import DiscoveryAgent
from ...core.cache import get_cache
from ...core.config import settings
from ...schemas.request import DiscoveryRequest

logger = logging.getLogger(__name__)
router = APIRouter()

_discovery_agent: DiscoveryAgent | None = None


def get_discovery_agent() -> DiscoveryAgent:
    global _discovery_agent
    if _discovery_agent is None:
        _discovery_agent = DiscoveryAgent(settings.agents_dir)
    return _discovery_agent


@router.post("/discover")
async def discover(request: DiscoveryRequest):
    cache_key = (
        "discover:"
        + hashlib.md5(
            request.model_dump_json().encode(), usedforsecurity=False
        ).hexdigest()
    )
    cache = get_cache()
    if cached := cache.get(cache_key):
        return cached

    agent = get_discovery_agent()
    try:
        result = await asyncio.wait_for(agent.run(request), timeout=30)
    except TimeoutError:
        raise HTTPException(
            status_code=504, detail="Discovery timed out — please try again"
        )
    except Exception as e:
        logger.error(f"Discovery agent failed: {e}")
        raise HTTPException(
            status_code=500, detail="Discovery failed — please try again"
        )

    cache[cache_key] = result
    return result
