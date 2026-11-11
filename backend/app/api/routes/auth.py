import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...core.errors import ApiError
from ...core.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH_V2,
    password_problem,
)
from ...core.rate_limit import (
    caller_key,
    login_locked,
    rate_limit,
    record_login_failure,
    too_many,
)
from ...core.session import Client, email_hint, issue_session, session_tokens
from ...core.session_payload import user_payload
from ...core.urls import public_url
from ...db.sessions_db import revoke_all
from ...db.users_db import (
    EmailInUseError,
    _verify,
    authenticate_user,
    bump_token_version,
    change_password,
    get_user_by_id,
    get_user_by_login,
    set_email,
)

router = APIRouter()

PASSWORD_DETAIL = {
    "password_too_short": f"Use at least {MIN_PASSWORD_LENGTH_V2} characters.",
    "password_too_long": f"Use at most {MAX_PASSWORD_LENGTH} characters.",
    "password_common": "That password is too common. Pick something less guessable.",
    "password_matches_identity": "Don't use your username or email as the password.",
}


class LoginRequest(BaseModel):
    username: str
    password: str
    client: Client = "web"
    device_name: str | None = Field(None, max_length=64)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    client: Client = "web"
    device_name: str | None = Field(None, max_length=64)


# A fixed bcrypt hash, verified when the login names no usable account so
# unknown, inactive and password-less logins cost the same time as a real one.
_DUMMY_HASH = "$2b$12$kRZsB.iPBmEFn5Bh.S/lAOYgfSJCh1jANaXySDq1FqSmN/zlVon9."


@router.post("/auth/login", dependencies=[Depends(rate_limit("login"))])
def login(req: LoginRequest, request: Request):
    # Per-IP attempts are the "login" bucket. Failures lock this account for
    # this IP (and, far higher, from everywhere), checked before bcrypt so a
    # guesser learns nothing; other IPs can't lock the real user out.
    caller = caller_key(request, None)
    # ``username`` may also be the account's email. The lock is keyed on the
    # resolved account, so alternating username and email gains nothing.
    found = get_user_by_login(req.username)
    lock_key = found["username"].lower() if found else req.username
    wait = login_locked(lock_key, caller)
    if wait is not None:
        raise too_many(wait)
    if found and found["is_active"] and found.get("password_hash") != "!":
        user = authenticate_user(found["username"], req.password)
    else:
        _verify(req.password, _DUMMY_HASH)  # timing parity, result ignored
        user = None
    if not user:
        record_login_failure(lock_key, caller)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if user.get("account_status", "active") == "pending":
        # only revealed once the password was right
        raise ApiError(
            403,
            "account_pending",
            "Confirm your email to finish creating your account.",
            email_hint=email_hint(user.get("email")),
        )
    return issue_session(user, req.client, req.device_name)


@router.post("/auth/change-password")
def change_password_endpoint(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    has_password = current_user.get("password_hash") != "!"
    if has_password and not authenticate_user(
        current_user["username"], req.current_password
    ):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    problem = password_problem(
        req.new_password,
        username=current_user["username"],
        email=current_user.get("email"),
    )
    if problem:
        raise ApiError(400, problem, PASSWORD_DETAIL[problem])
    change_password(current_user["username"], req.new_password)
    # Signs every other session out; the token below keeps this one alive.
    bump_token_version(current_user["id"])
    revoke_all(current_user["id"])
    user = get_user_by_id(current_user["id"])
    return session_tokens(user, req.client, req.device_name)


@router.get("/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    return user_payload(current_user)


# local@domain.tld — deliberately simple; the mail server has the final word
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


class EmailUpdate(BaseModel):
    email: str = Field("", max_length=254)


def _queue_verification(user: dict, email: str, background: BackgroundTasks) -> bool:
    """Queue a verify link for a newly set email; False when no account-email
    sender (or token store) is available yet."""
    try:
        from ...db.account_tokens_db import issue_token
        from ...services.account_email import (
            email_delivery_available,
            send_account_email,
        )
    except ImportError:
        return False
    if not email_delivery_available():
        return False
    from .signup import address_allowed

    if not address_allowed(email, "verify"):
        return True  # silent per-address limit: answers as if sent
    token = issue_token(user["id"], "verify_email", email)
    background.add_task(
        send_account_email,
        "verify",
        email,
        link=public_url(f"/verify?token={token}"),
        locale=user.get("locale"),
        username=user["username"],
    )
    return True


@router.put("/auth/email", dependencies=[Depends(rate_limit("light_ai"))])
def update_email(
    req: EmailUpdate,
    background: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """Set or clear (empty string) the account's email, used for fare alerts.
    A changed email starts unverified and gets a verify link when email
    delivery is available."""
    email = req.email.strip().lower() or None
    if email and not _EMAIL_RE.match(email):
        raise HTTPException(
            status_code=422, detail="That doesn't look like an email address."
        )
    previous = (current_user.get("email") or "").lower() or None
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
    sent = False
    if email and email != previous:
        sent = _queue_verification(current_user, email, background)
    user = get_user_by_id(current_user["id"]) or {}
    return {
        "email": email,
        "email_verified": bool(user.get("email_verified")),
        "verification_sent": sent,
    }
