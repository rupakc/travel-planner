import asyncio
import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException

from ...agents.discovery_agent import DiscoveryAgent
from ...core import llm
from ...core.auth import get_optional_user
from ...core.cache import get_cache, request_digest
from ...core.config import settings
from ...db.taste_db import derive_taste_context
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
async def discover(
    request: DiscoveryRequest, user: dict | None = Depends(get_optional_user)
):
    # Signed-in callers get their Taste Graph summary (never client-supplied);
    # anonymous calls and users without signals behave exactly as before.
    taste = None
    if user:
        try:
            taste = derive_taste_context(user["username"])
        except Exception:  # noqa: BLE001
            logger.warning("taste context failed", exc_info=True)
    cache_key = "discover:" + request_digest(request)
    if taste:
        cache_key += ":t" + hashlib.sha256(taste.encode()).hexdigest()[:16]
    cache = get_cache()
    if cached := cache.get(cache_key):
        return cached

    agent = get_discovery_agent()
    try:
        result = await asyncio.wait_for(
            agent.run(request, taste_context=taste), timeout=30
        )
    except TimeoutError:
        raise HTTPException(
            status_code=504, detail="Discovery timed out — please try again"
        )
    except Exception as e:
        logger.error(f"Discovery agent failed: {e}")
        raise HTTPException(
            status_code=500, detail="Discovery failed — please try again"
        )

    if paused := llm.user_error(result):
        raise HTTPException(status_code=503, detail=paused["error"])
    cache[cache_key] = result
    return result
