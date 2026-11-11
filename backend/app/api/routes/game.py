from fastapi import APIRouter, Depends, Response

from ...core.auth import get_current_user
from ...core.config import settings
from ...core.errors import ApiError
from ...db import game_db
from ...game import engine

router = APIRouter()


def _require_enabled() -> None:
    if not settings.game_enabled:
        raise ApiError(404, "game_disabled", "Not found")


@router.get("/game/me")
def game_me(user: dict = Depends(get_current_user)) -> dict:
    _require_enabled()
    return engine.summary(user["id"], hidden=game_db.hide_game(user["id"]))


@router.get("/game/catalog")
def game_catalog(response: Response) -> dict:
    _require_enabled()
    response.headers["Cache-Control"] = "max-age=300"
    return engine.catalog()
