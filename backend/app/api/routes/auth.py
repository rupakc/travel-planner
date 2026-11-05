import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...core.auth import MIN_PASSWORD_LENGTH, create_access_token, get_current_user
from ...core.rate_limit import rate_limit
from ...db.users_db import (
    EmailInUseError,
    authenticate_user,
    change_password,
    set_email,
)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/login")
def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(
        {
            "sub": user["username"],
            "is_admin": user["is_admin"],
            "is_first_login": user["is_first_login"],
        }
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "username": user["username"],
            "is_admin": user["is_admin"],
            "requires_password_change": user["is_first_login"],
            "email": user.get("email"),
        },
    }


@router.post("/auth/change-password")
def change_password_endpoint(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    user = authenticate_user(current_user["username"], req.current_password)
    if not user:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(req.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"New password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    change_password(current_user["username"], req.new_password)
    # Issue a new token with is_first_login=False
    token = create_access_token(
        {
            "sub": current_user["username"],
            "is_admin": current_user["is_admin"],
            "is_first_login": False,
        }
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get("/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    return {
        "username": current_user["username"],
        "is_admin": current_user["is_admin"],
        "requires_password_change": current_user["is_first_login"],
        "email": current_user.get("email"),
    }


# local@domain.tld — deliberately simple; the mail server has the final word
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


class EmailUpdate(BaseModel):
    email: str = Field("", max_length=254)


@router.put("/auth/email", dependencies=[Depends(rate_limit("light_ai"))])
def update_email(req: EmailUpdate, current_user: dict = Depends(get_current_user)):
    """Set or clear (empty string) the account's email, used for fare alerts."""
    email = req.email.strip().lower() or None
    if email and not _EMAIL_RE.match(email):
        raise HTTPException(
            status_code=422, detail="That doesn't look like an email address."
        )
    try:
        set_email(current_user["username"], email)
    except EmailInUseError:
        raise HTTPException(
            status_code=409, detail="Another account already uses that email."
        )
    if email is None:  # nowhere to send fare or price alerts any more
        from ...db import fare_watch_db, price_watch_db

        fare_watch_db.disable_email_for_user(current_user["id"])
        price_watch_db.disable_email_for_user(current_user["id"])
    return {"email": email}
