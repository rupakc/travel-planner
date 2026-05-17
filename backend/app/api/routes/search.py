import hashlib
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from ...schemas.request import TravelSearchRequest
from ...agents.orchestrator import TravelOrchestrator
from ...core.config import settings
from ...core.cache import get_cache

router = APIRouter()


def get_orchestrator() -> TravelOrchestrator:
    return TravelOrchestrator(agents_dir=settings.agents_dir)


@router.post("/search")
async def search(request: TravelSearchRequest):
    """Stream travel planning results; cache full event sequence for 30 min."""
    cache_key = "search:" + hashlib.md5(request.model_dump_json().encode(), usedforsecurity=False).hexdigest()  # nosec B324
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
async def search_sync(request: TravelSearchRequest):
    """Non-streaming search that waits for all results. For testing."""
    orchestrator = get_orchestrator()
    result = await orchestrator.run(request)
    return result
