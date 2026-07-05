import hashlib
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ...agents.orchestrator import TravelOrchestrator
from ...core.auth import get_optional_user
from ...core.cache import get_cache
from ...core.config import settings
from ...db.taste_db import derive_taste_context
from ...schemas.request import TravelSearchRequest

logger = logging.getLogger(__name__)

router = APIRouter()


def get_orchestrator() -> TravelOrchestrator:
    return TravelOrchestrator(agents_dir=settings.agents_dir)


def _is_cacheable_run(events: list[str]) -> bool:
    """Only fully-successful, complete runs may be cached and replayed."""
    saw_done = False
    for chunk in events:
        if not chunk.startswith("data: "):
            continue
        try:
            event = json.loads(chunk[len("data: ") :].strip())
        except (ValueError, TypeError):
            continue
        if event.get("type") == "done":
            saw_done = True
        data = event.get("data")
        if isinstance(data, dict) and data.get("error"):
            return False
    return saw_done


def _apply_taste_context(request: TravelSearchRequest, user: dict | None) -> None:
    """Overwrite taste_context from the user's Taste Graph (never trust client)."""
    request.taste_context = derive_taste_context(user["username"]) if user else None


@router.post("/search")
async def search(
    request: TravelSearchRequest,
    user: dict | None = Depends(get_optional_user),
):
    """Stream travel planning results; cache full event sequence for 30 min."""
    _apply_taste_context(request, user)
    cache_key = (
        "search:"
        + hashlib.md5(
            request.model_dump_json().encode(), usedforsecurity=False
        ).hexdigest()
    )
    cache = get_cache()

    async def generate():
        cached = cache.get(cache_key)
        if cached:
            # Replay cached events instantly
            for chunk in cached:
                yield chunk
            return

        orchestrator = get_orchestrator()
        collected: list[str] = []
        async for chunk in orchestrator.stream_run(request):
            if not chunk.startswith(": "):  # don't cache keepalive comments
                collected.append(chunk)
            yield chunk

        # NEVER cache a run containing failures — a cached error sequence is
        # replayed verbatim for 30 minutes, so one transient failure would
        # keep "failing" on every retry long after the cause is gone.
        if _is_cacheable_run(collected):
            cache[cache_key] = collected
        else:
            logger.warning(
                "Search run had errored sections or ended early — not cached"
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/search/sync")
async def search_sync(
    request: TravelSearchRequest,
    user: dict | None = Depends(get_optional_user),
):
    """Non-streaming search that waits for all results. For testing."""
    _apply_taste_context(request, user)
    orchestrator = get_orchestrator()
    result = await orchestrator.run(request)
    return result
