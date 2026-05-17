"""Admin-only user management endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core.auth import require_admin
from ...db.users_db import (
    create_user,
    get_all_users,
    get_user_by_username,
    deactivate_user,
    reactivate_user,
)

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: str | None = None
    is_admin: bool = False


@router.post("/admin/users", status_code=201)
async def admin_create_user(
    req: CreateUserRequest,
    _admin: dict = Depends(require_admin),
):
    if get_user_by_username(req.username):
        raise HTTPException(status_code=409, detail="Username already exists")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Temporary password must be at least 6 characters")
    user = create_user(
        username=req.username,
        password=req.password,
        email=req.email,
        is_admin=req.is_admin,
        is_first_login=True,
    )
    return _safe(user)


@router.get("/admin/users")
async def admin_list_users(_admin: dict = Depends(require_admin)):
    return [_safe(u) for u in get_all_users()]


@router.delete("/admin/users/{username}", status_code=204)
async def admin_deactivate_user(
    username: str,
    admin: dict = Depends(require_admin),
):
    if username == admin["username"]:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    if not get_user_by_username(username):
        raise HTTPException(status_code=404, detail="User not found")
    deactivate_user(username)


@router.post("/admin/users/{username}/reactivate", status_code=200)
async def admin_reactivate_user(
    username: str,
    _admin: dict = Depends(require_admin),
):
    if not get_user_by_username(username):
        raise HTTPException(status_code=404, detail="User not found")
    reactivate_user(username)
    return {"status": "reactivated"}


def _safe(user: dict) -> dict:
    """Strip password_hash before returning to client."""
    return {k: v for k, v in user.items() if k != "password_hash"}
