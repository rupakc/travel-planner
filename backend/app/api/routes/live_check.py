"""POST /api/live-check — "Search the web now" for one of the caller's
watches: a Gemini call grounded with Google Search, answered to that user
once. Nothing is stored, cached or fed to alerts (Google's Search grounding
terms; see services/live_check.py and docs/Trip-Planning-Features.md, "Live
web check and Near me")."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ...core import llm
from ...core.auth import get_current_user
from ...db import fare_watch_db, price_watch_db
from ...services import live_check

router = APIRouter()

FAILED = {
    "code": "live_check_failed",
    "message": "We couldn't get a live answer from the web just now. Try again.",
}


class LiveCheckRequest(BaseModel):
    # No free-text prompt: the server builds it from the stored watch
    model_config = ConfigDict(extra="forbid")

    kind: Literal["flight", "hotel", "activity", "trip"]
    watch_id: int = Field(..., ge=1)


def _owned(kind: str, watch_id: int, user: dict) -> dict:
    """The caller's watch of that kind; anything else is the same 404."""
    if kind == "flight":
        watch = fare_watch_db.get_watch_for_user(watch_id, user["id"])
    else:
        watch = price_watch_db.get_watch_for_user(watch_id, user["id"])
        if watch is not None and watch.get("kind") != kind:
            watch = None
    if watch is None:
        raise HTTPException(status_code=404, detail="Watch not found")
    return watch


@router.post("/live-check")
async def live_check_now(
    body: LiveCheckRequest, user: dict = Depends(get_current_user)
):
    watch = _owned(body.kind, body.watch_id, user)
    now = datetime.now(UTC)
    system, prompt = live_check.build_prompt(
        body.kind, watch, today=now.date().isoformat()
    )
    try:
        out = await llm.generate_grounded(
            prompt, tool="search", system=system, label=f"live_check_{body.kind}"
        )
    except llm.LLMError as e:
        if e.user_facing:
            raise HTTPException(
                status_code=503, detail={"code": e.user_code, "message": str(e)}
            ) from e
        raise HTTPException(status_code=502, detail=FAILED) from e
    sources, index = live_check.sources_from(out.chunks)
    summary = out.text.strip()
    if not summary or not sources:
        # Not grounded (or no answer): nothing we could show with sources
        raise HTTPException(status_code=502, detail=FAILED)
    return {
        "kind": body.kind,
        "watch_id": body.watch_id,
        "checked_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "summary": summary,
        "quotes": live_check.parse_quotes(out.text, out.supports, index),
        "sources": sources,
        "searched_for": out.search_queries,
        "disclaimer": live_check.DISCLAIMER,
    }
