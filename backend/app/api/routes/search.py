import hashlib

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ...agents.orchestrator import TravelOrchestrator
from ...core.auth import get_optional_user
from ...core.cache import get_cache
from ...core.config import settings
from ...db.taste_db import derive_taste_context
from ...schemas.request import TravelSearchRequest

router = APIRouter()


def get_orchestrator() -> TravelOrchestrator:
    return TravelOrchestrator(agents_dir=settings.agents_dir)


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

        cache[cache_key] = collected

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
