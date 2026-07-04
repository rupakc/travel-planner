from fastapi import APIRouter, Depends

from ...core.auth import get_current_user
from ...db.taste_db import clear_taste_profile, derive_taste_context, get_taste_profile

router = APIRouter()


@router.get("/taste-profile")
async def read_taste_profile(current_user: dict = Depends(get_current_user)):
    username = current_user["username"]
    profile = get_taste_profile(username)
    return {**profile, "context": derive_taste_context(username)}


@router.delete("/taste-profile")
async def reset_taste_profile(current_user: dict = Depends(get_current_user)):
    deleted = clear_taste_profile(current_user["username"])
    return {"success": True, "deleted_signals": deleted}
