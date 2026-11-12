"""Play (Phase 5): quiz sessions, history and state. Contract: docs/Social-API.md.

Every route needs sign-in and the ``play`` bucket (router dependency in
main.py). They answer 404 ``play_disabled`` while ``PLAY_ENABLED`` (or
``GAME_ENABLED``) is off and 403 ``game_hidden`` for users who hide Play and
points. A quiz makes no AI call.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...core.config import settings
from ...core.errors import ApiError
from ...db import game_db
from ...game.quiz import service

router = APIRouter()


def play_enabled() -> bool:
    return bool(settings.play_enabled and settings.game_enabled)


def require_play(user: dict = Depends(get_current_user)) -> dict:
    if not play_enabled():
        raise ApiError(404, "play_disabled", "Not found")
    if game_db.hide_game(user["id"]):
        raise ApiError(
            403, "game_hidden", "Play and points are hidden in your account."
        )
    return user


class StartQuizBody(BaseModel):
    mode: str = Field(max_length=16)
    pack: str | None = Field(None, max_length=16)
    locale: str | None = Field(None, max_length=8)


class AnswerBody(BaseModel):
    index: int
    choice: str = Field(max_length=8)


@router.get("/play/state")
def play_state(user: dict = Depends(require_play)) -> dict:
    return service.state(user["id"])


@router.post("/play/quiz")
def start_quiz(body: StartQuizBody, user: dict = Depends(require_play)) -> dict:
    return service.start(user["id"], body.mode, body.pack)


@router.get("/play/quiz/{session_id}")
def get_quiz(session_id: str, user: dict = Depends(require_play)) -> dict:
    return service.get(user["id"], session_id)


@router.post("/play/quiz/{session_id}/answer")
def answer_quiz(
    session_id: str, body: AnswerBody, user: dict = Depends(require_play)
) -> dict:
    return service.answer(user["id"], session_id, body.index, body.choice)


@router.get("/play/history")
def play_history(
    limit: int = Query(20, ge=1, le=50), user: dict = Depends(require_play)
) -> dict:
    return {"sessions": service.history(user["id"], limit)}
