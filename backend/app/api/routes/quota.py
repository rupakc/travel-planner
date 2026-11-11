import asyncio

from fastapi import APIRouter, Depends

from ...core import ai_quota
from ...core.auth import get_current_user

router = APIRouter()


@router.get("/account/quota")
async def get_quota(user: dict = Depends(get_current_user)) -> dict:
    return await asyncio.to_thread(ai_quota.usage, user)
