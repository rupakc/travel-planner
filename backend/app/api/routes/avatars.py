import asyncio
import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse

from ...core.auth import get_current_user
from ...core.errors import ApiError
from ...core.rate_limit import rate_limit
from ...services import avatar as svc

router = APIRouter()


@router.put("/account/avatar", dependencies=[Depends(rate_limit("account"))])
async def upload_avatar(
    file: UploadFile = File(...), user: dict = Depends(get_current_user)
):
    data = await file.read(svc.MAX_BYTES + 1)
    if len(data) > svc.MAX_BYTES:
        raise svc._too_large()
    webp = await asyncio.to_thread(svc.process_upload, data, file.content_type or "")
    url = await asyncio.to_thread(svc.save_avatar, user["id"], webp, "upload")
    return {"avatar_url": url}


@router.delete("/account/avatar", dependencies=[Depends(rate_limit("account"))])
def delete_avatar(user: dict = Depends(get_current_user)):
    svc.remove_avatar(user["id"])
    return {"avatar_url": None}


@router.get("/avatars/{user_id}.webp")
async def get_avatar(user_id: str):
    try:
        canonical = str(uuid.UUID(user_id))
    except ValueError:
        raise ApiError(404, "not_found", "Not found")
    if canonical != user_id:
        raise ApiError(404, "not_found", "Not found")
    path = svc.avatar_path(canonical)
    if not path.is_file():
        raise ApiError(404, "not_found", "Not found")
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
