"""Native accounts: sign-up, email verification and password reset.

Nothing here reveals whether an email address has an account: resend and
reset-request always answer 202, and sign-up with an already registered
email answers exactly like a new sign-up (the owner gets an "already
registered" email instead). Emails are sent in the background, after the
response, and every send also counts against a silent per-address limit
(``email_address``, keyed by the address's SHA-256) that skips the send but
still answers 202. Tokens are never logged.
"""

import hashlib
import logging
import re
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field

from ...core.auth import get_current_user, get_optional_user
from ...core.config import settings
from ...core.errors import ApiError
from ...core.passwords import password_problem
from ...core.rate_limit import caller_key, try_consume
from ...core.session import Client, issue_session
from ...core.urls import public_url
from ...db import account_tokens_db as tokens
from ...db import invites_db, users_db
from ...db.reserved_usernames import RESERVED_USERNAMES
from ...db.sessions_db import revoke_all
from ...game import hooks
from ...services import account_email
from .account import _display_name
from .auth import _EMAIL_RE, PASSWORD_DETAIL

logger = logging.getLogger(__name__)

router = APIRouter()

_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")
_LOCALES = frozenset({"en", "es", "de", "fr", "hi", "zh", "bn"})

_TOKEN_ERRORS = {
    "invalid": (400, "token_invalid", "This link is not valid."),
    "expired": (410, "token_expired", "This link has expired. Ask for a new one."),
    "used": (409, "token_used", "This link was already used."),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _ttl_s() -> int:
    return int(settings.account_token_ttl_minutes) * 60


def _limited(bucket: str):
    """Rate-limit dependency answering the contract ``429 rate_limited``."""

    async def enforce(
        request: Request, user: dict | None = Depends(get_optional_user)
    ) -> None:
        wait = try_consume(bucket, caller_key(request, user))
        if wait is not None:
            raise ApiError(
                429,
                "rate_limited",
                f"Too many requests — please wait {wait} seconds and try again.",
                headers={"Retry-After": str(wait)},
            )

    return enforce


def _require_email() -> None:
    if not account_email.email_delivery_available():
        raise ApiError(
            503, "email_unavailable", "Email can't be sent right now. Try again later."
        )


def _locale(value: str | None) -> str | None:
    v = (value or "").strip().lower()
    return v if v in _LOCALES else None


def address_allowed(to: str, kind: str) -> bool:
    """Take one ``email_address`` token for this address (keyed by its
    SHA-256). False when over the limit: the caller skips the send silently.
    Every account email passes through here."""
    key = hashlib.sha256(to.strip().lower().encode()).hexdigest()
    if try_consume("email_address", key) is not None:
        logger.info("account_email.address_limited kind=%s", kind)
        return False
    return True


def _send(
    background: BackgroundTasks,
    kind: str,
    to: str,
    *,
    link: str | None,
    locale: str | None,
    username: str,
) -> None:
    """Queue an account email unless this address hit its (silent) limit."""
    if not address_allowed(to, kind):
        return
    background.add_task(
        account_email.send_account_email,
        kind,
        to,
        link=link,
        locale=locale,
        username=username,
    )


def _send_verify(background, user: dict, email: str, locale: str | None) -> None:
    token = tokens.issue_token(user["id"], "verify_email", email, now=_now())
    _send(
        background,
        "verify",
        email,
        link=public_url(f"/verify?token={token}"),
        locale=locale or user.get("locale"),
        username=user["username"],
    )


def _token_error(err: tokens.TokenError) -> ApiError:
    status, code, detail = _TOKEN_ERRORS[err.reason]
    return ApiError(status, code, detail)


def _password(password: str, username: str, email: str | None) -> None:
    problem = password_problem(password, username=username, email=email)
    if problem:
        raise ApiError(422, problem, PASSWORD_DETAIL[problem])


# ── sign-up ──────────────────────────────────────────────────────────────────


class SignupRequest(BaseModel):
    username: str = Field(..., max_length=256)
    email: str = Field(..., max_length=1024)
    password: str = Field(..., max_length=1024)
    display_name: str | None = Field(None, max_length=1024)
    invite_code: str | None = Field(None, max_length=64)
    locale: str | None = Field(None, max_length=16)
    client: Client = "web"


def _clean_signup(req: SignupRequest) -> tuple[str, str, str | None]:
    username = req.username.strip().lower()
    if not _USERNAME_RE.match(username):
        raise ApiError(
            422,
            "username_invalid",
            "Use 3–20 letters, digits or underscores for the username.",
        )
    if username in RESERVED_USERNAMES:
        raise ApiError(422, "username_reserved", "That username is reserved.")
    email = req.email.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise ApiError(422, "email_invalid", "That doesn't look like an email address.")
    _password(req.password, username, email)
    display = None if req.display_name is None else _display_name(req.display_name)
    return username, email, display


@router.post(
    "/auth/signup", status_code=202, dependencies=[Depends(_limited("signup"))]
)
def signup(req: SignupRequest, background: BackgroundTasks):
    if not settings.signup_enabled:  # operator opt-in (SIGNUP_ENABLED)
        raise ApiError(
            503, "email_unavailable", "Email can't be sent right now. Try again later."
        )
    _require_email()
    username, email, display = _clean_signup(req)
    locale = _locale(req.locale)
    accepted = {"status": "verification_sent", "email": email, "expires_in": _ttl_s()}

    code = (req.invite_code or "").strip()
    if settings.signup_mode == "invite":
        if not code:
            raise ApiError(403, "invite_required", "Sign-up needs an invite code.")
        if invites_db.check_invite(code) is None:
            raise ApiError(403, "invite_invalid", "That invite code is not valid.")

    owner = users_db.get_user_by_email(email)
    # Re-submitting one's own pending sign-up (same username + email) is not
    # "taken": create_pending_user replaces that pending row.
    resubmit = (
        owner is not None
        and owner.get("account_status") == "pending"
        and owner["username"].lower() == username
    )
    if not resubmit and not users_db.username_available(username, _now()):
        raise ApiError(409, "username_taken", "That username is taken.")

    def already_registered(owner: dict | None) -> dict:
        if owner and owner["is_active"]:
            _send(
                background,
                "already_registered",
                email,
                link=None,
                locale=locale or owner.get("locale"),
                username=owner["username"],
            )
        return accepted

    if owner and owner.get("account_status") != "pending":
        users_db._hash(req.password)  # same bcrypt cost as a real sign-up
        return already_registered(owner)

    invite_id = None
    if settings.signup_mode == "invite":
        invite_id = invites_db.consume_invite(code)
        if invite_id is None:  # lost the race for the last use
            raise ApiError(403, "invite_invalid", "That invite code is not valid.")
    try:
        user = users_db.create_pending_user(
            username, email, req.password, display, locale, invite_id
        )
    except users_db.UsernameTakenError:
        if invite_id is not None:
            logger.info("signup.race_lost invite_use_kept invite_id=%s", invite_id)
        raise ApiError(409, "username_taken", "That username is taken.")
    except users_db.EmailInUseError:
        if invite_id is not None:
            logger.info("signup.race_lost invite_use_kept invite_id=%s", invite_id)
        return already_registered(users_db.get_user_by_email(email))
    _send_verify(background, user, email, locale)
    return accepted


# ── verify ───────────────────────────────────────────────────────────────────


class EmailRequest(BaseModel):
    email: str = Field(..., max_length=1024)
    locale: str | None = Field(None, max_length=16)


@router.post(
    "/auth/verify-email/resend",
    status_code=202,
    dependencies=[Depends(_limited("auth_email"))],
)
def resend_verification(req: EmailRequest, background: BackgroundTasks):
    _require_email()
    email = req.email.strip().lower()
    user = users_db.get_user_by_email(email) if email else None
    if user and user["is_active"] and not user.get("email_verified"):
        _send_verify(background, user, user["email"], _locale(req.locale))
    return {"status": "verification_sent"}


class VerifyRequest(BaseModel):
    token: str = Field(..., max_length=256)
    client: Client = "web"
    device_name: str | None = Field(None, max_length=64)


@router.post("/auth/verify-email")
def verify_email(req: VerifyRequest):
    res = tokens.redeem_token(req.token, "verify_email", _now())
    if isinstance(res, tokens.TokenError):
        raise _token_error(res)
    user = users_db.get_user_by_id(res["user_id"])
    if not user:
        raise _token_error(tokens.TokenError("invalid"))
    session = None
    if user.get("account_status") == "pending":
        if (user.get("email") or "").lower() != res["email"]:
            raise ApiError(409, "email_changed", "This link was for another email.")
        users_db.activate_user(user["id"], res["email"])
        game = hooks.on_email_verified(user["id"])
        user = users_db.get_user_by_id(user["id"])
        if user["is_active"]:
            session = issue_session(user, req.client, req.device_name)
    else:
        # an OAuth sign-up with an untrusted provider email has no email until
        # this link proves it (and only if nobody else holds it by now)
        if not users_db.mark_email_verified(
            user["id"], res["email"]
        ) and not users_db.claim_verified_email(user["id"], res["email"]):
            raise ApiError(409, "email_changed", "This link was for another email.")
        game = hooks.on_email_verified(user["id"])
    return {"status": "verified", "session": session, "game": game}


# ── password reset ───────────────────────────────────────────────────────────


@router.post(
    "/auth/password-reset/request",
    status_code=202,
    dependencies=[Depends(_limited("auth_email"))],
)
def password_reset_request(req: EmailRequest, background: BackgroundTasks):
    _require_email()
    email = req.email.strip().lower()
    user = users_db.get_user_by_email(email) if email else None
    # Only to a proven address (or a pending sign-up, which reset activates):
    # an active account's unverified email may be someone else's claim.
    if (
        user
        and user["is_active"]
        and (user.get("email_verified") or user.get("account_status") == "pending")
    ):
        token = tokens.issue_token(user["id"], "reset_password", email, now=_now())
        _send(
            background,
            "reset",
            user["email"],
            link=public_url(f"/reset-password?token={token}"),
            locale=_locale(req.locale) or user.get("locale"),
            username=user["username"],
        )
    return {"status": "reset_sent"}


class ResetConfirm(BaseModel):
    token: str = Field(..., max_length=256)
    new_password: str = Field(..., max_length=1024)
    client: Client = "web"
    device_name: str | None = Field(None, max_length=64)


@router.post("/auth/password-reset/confirm")
def password_reset_confirm(req: ResetConfirm):
    found = tokens.peek_token(req.token, "reset_password", _now())
    if isinstance(found, tokens.TokenError):
        raise _token_error(found)
    user = users_db.get_user_by_id(found["user_id"])
    # The link went to the address the account had then; a changed (or
    # deactivated) account doesn't honour it.
    if (
        not user
        or not user["is_active"]
        or (user.get("email") or "").lower() != found["email"]
    ):
        raise _token_error(tokens.TokenError("invalid"))
    # Check the password first: a rejected one doesn't use the link up.
    _password(req.new_password, user["username"], user.get("email"))
    res = tokens.redeem_token(req.token, "reset_password", _now())
    if isinstance(res, tokens.TokenError):
        raise _token_error(res)
    users_db.change_password(user["username"], req.new_password)
    users_db.bump_token_version(user["id"])
    revoke_all(user["id"])
    # The email is proven: a pending account becomes active and verified. An
    # active account's unverified email is never marked verified by a reset.
    if user.get("account_status") == "pending":
        users_db.activate_user(user["id"], res["email"])
        hooks.on_email_verified(user["id"])
    user = users_db.get_user_by_id(user["id"])
    return {
        "status": "password_reset",
        "session": issue_session(user, req.client, req.device_name),
    }


# ── verify the signed-in account's email ─────────────────────────────────────


class LocaleBody(BaseModel):
    locale: str | None = Field(None, max_length=16)


@router.post(
    "/account/email/verify",
    status_code=202,
    dependencies=[Depends(_limited("auth_email"))],
)
def account_email_verify(
    background: BackgroundTasks,
    body: LocaleBody | None = None,
    user: dict = Depends(get_current_user),
):
    email = (user.get("email") or "").strip().lower()
    if not email:
        raise ApiError(422, "no_email", "Add an email address first.")
    if user.get("email_verified"):
        raise ApiError(409, "already_verified", "Your email is already confirmed.")
    _require_email()
    _send_verify(background, user, email, _locale(body.locale if body else None))
    return {"status": "verification_sent", "email": email, "expires_in": _ttl_s()}
