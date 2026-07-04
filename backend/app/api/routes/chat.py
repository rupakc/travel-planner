import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...agents.chat_agent import ChatAgent
from ...core.auth import get_current_user
from ...core.config import settings
from ...db.preferences_db import get_preferences

router = APIRouter()

logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    selections: dict = {}
    search_results: dict = {}
    session_context: dict = {}


@router.post("/chat")
async def chat(request: ChatRequest, user: dict = Depends(get_current_user)):
    """Stream a conversational travel planning response."""
    prefs = get_preferences(user["username"])
    agent = ChatAgent(agents_dir=settings.agents_dir)
    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    async def generate():
        # An uncaught exception here would silently truncate the SSE stream —
        # the user would see a blank reply. Always close with error + done.
        try:
            async for chunk in agent.stream(
                messages,
                preferences=prefs,
                selections=request.selections,
                search_results=request.search_results,
                session_context=request.session_context,
            ):
                yield f"data: {chunk}\n\n"
        except Exception as e:
            logger.exception("Chat stream failed")
            fallback = {
                "type": "delta",
                "text": (
                    "Sorry — something went wrong while answering that. "
                    "Please try again."
                ),
            }
            yield f"data: {json.dumps(fallback)}\n\n"
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
