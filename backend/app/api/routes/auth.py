from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core.auth import create_access_token, get_current_user
from ...db.users_db import authenticate_user, change_password

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/login")
async def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token({
        "sub": user["username"],
        "is_admin": user["is_admin"],
        "is_first_login": user["is_first_login"],
    })
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "username": user["username"],
            "is_admin": user["is_admin"],
            "requires_password_change": user["is_first_login"],
        },
    }


@router.post("/auth/change-password")
async def change_password_endpoint(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    user = authenticate_user(current_user["username"], req.current_password)
    if not user:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    change_password(current_user["username"], req.new_password)
    # Issue a new token with is_first_login=False
    token = create_access_token({
        "sub": current_user["username"],
        "is_admin": current_user["is_admin"],
        "is_first_login": False,
    })
    return {"access_token": token, "token_type": "bearer"}


@router.get("/auth/me")
async def me(current_user: dict = Depends(get_current_user)):
    return {
        "username": current_user["username"],
        "is_admin": current_user["is_admin"],
        "requires_password_change": current_user["is_first_login"],
    }
