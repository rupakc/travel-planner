"""OAuth sign-in: provider listing, authorization-code flow with PKCE + state,
one-time handoff codes, account completion, linking and native ID tokens.

Nothing secret ever travels in a URL except the contract's single-use,
short-lived ``state`` / handoff ``code`` / link ticket; nothing secret is logged.
"""

from __future__ import annotations

import dataclasses
import hmac
import logging
import re
import secrets
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...core.config import settings
from ...core.errors import ApiError
from ...core.rate_limit import rate_limit
from ...core.session import MOBILE_CLIENTS, issue_session
from ...core.urls import public_base_url, public_url
from ...db import invites_db, oauth_db
from ...game import hooks
from ...services.oauth import flow, registry
from ...services.oauth.base import OAuthError, pkce_challenge, pkce_verifier
from ...services.oauth.secrets_box import seal
from .account import _display_name

logger = logging.getLogger(__name__)

router = APIRouter()

COOKIE = "tp_oauth"
LINK_COOKIE = "tp_oauth_link"
COOKIE_PATH = "/api/auth/oauth"
STATE_TTL_S = 600
HANDOFF_TTL_S = 120
SIGNUP_TTL_S = 1800
LINK_TTL_S = 300
NATIVE_PROVIDERS = ("apple", "google")
LOCALES = frozenset({"en", "es", "de", "fr", "hi", "zh", "bn"})
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_CANCEL_ERRORS = {"access_denied", "user_cancelled_authorize", "user_denied"}
# the contract's callback error codes; anything else reaches clients as provider_error
CALLBACK_ERRORS = frozenset(
    {"cancelled", "state_invalid", "provider_error", "provider_unavailable",
     "email_in_use_unverified", "identity_in_use", "account_inactive", "bad_request"}
)  # fmt: skip

_oauth_limit = [Depends(rate_limit("oauth"))]
_logged_config = False


def _now() -> datetime:
    return datetime.now(UTC)


def _provider(p: str):
    """The provider object, or None when absent/broken (never raises)."""
    try:
        return registry.get_provider(p)
    except Exception:
        logger.exception("oauth.provider_load_failed provider=%s", p)
        return None


def _configured(provider) -> bool:
    try:
        return bool(provider and provider.configured())
    except Exception:
        return False


def _native(p: str, provider) -> bool:
    if p not in NATIVE_PROVIDERS or not provider:
        return False
    try:
        return bool(provider.native_configured())
    except Exception:
        return False


def _callback_uri(p: str) -> str:
    return public_url(f"/api/auth/oauth/{p}/callback")


def _web_final() -> str:
    return public_url("/auth/callback")


def _allowed_redirects() -> list[str]:
    return [*settings.oauth_mobile_redirects, _web_final()]


def _redirect(final: str, **params: str) -> RedirectResponse:
    if "error" in params and params["error"] not in CALLBACK_ERRORS:
        params["error"] = "provider_error"
    sep = "&" if "?" in final else "?"
    return RedirectResponse(f"{final}{sep}{urlencode(params)}", status_code=302)


def _safe_return_to(raw: str | None, default: str = "/") -> str | None:
    """A same-origin path, or None when it points anywhere else."""
    if raw is None or raw == "":
        return default
    if (
        len(raw) > 512
        or not raw.startswith("/")
        or raw.startswith("//")
        or "\\" in raw
        or any(ord(c) < 32 for c in raw)
    ):
        return None
    return raw


def _locale(raw: str | None) -> str | None:
    base = (raw or "").strip().lower().replace("_", "-").split("-")[0]
    return base if base in LOCALES else None


def _game(user_id: str, delta: dict | None = None) -> dict | None:
    if not settings.game_enabled:
        return None
    if delta:
        return delta
    try:
        from ...db import game_db
        from ...db.database import get_connection

        with get_connection() as conn:
            xp = game_db.total_xp(conn, user_id)
    except Exception:
        xp = 0
    return {"xp": xp, "awards": [], "badges": [], "level_up": None}


def _secure() -> bool:
    return public_base_url().startswith("https://")


def _set_binding_cookie(resp, name: str, value: str, max_age: int) -> None:
    secure = _secure()
    resp.set_cookie(
        name,
        value,
        max_age=max_age,
        path=COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite="none" if secure else "lax",
    )


def _code_invalid() -> ApiError:
    return ApiError(400, "code_invalid", "This sign-in link has expired. Try again.")


# ── Discovery ────────────────────────────────────────────────────────────────


@router.get("/auth/providers")
def list_providers():
    global _logged_config
    out = []
    for p in registry.PROVIDER_ORDER:
        provider = _provider(p)
        configured = _configured(provider)
        out.append(
            {
                "id": p,
                "configured": configured,
                "start_url": f"/api/auth/oauth/{p}/start" if configured else None,
                "id_token": _native(p, provider),
            }
        )
    if not _logged_config:
        _logged_config = True
        on = [x["id"] for x in out if x["configured"]]
        logger.info(
            "oauth.configured providers=%s redirect_uris=%s",
            on,
            [_callback_uri(p) for p in on],
        )
    return {"providers": out}


# ── Browser flow ─────────────────────────────────────────────────────────────


@router.get("/auth/oauth/{p}/start", dependencies=_oauth_limit)
def start(
    request: Request,
    p: str,
    client: str = "web",
    return_to: str | None = None,
    challenge: str | None = None,
    redirect_uri: str | None = None,
    link: str | None = None,
):
    if p not in registry.PROVIDER_ORDER:
        raise ApiError(404, "provider_unknown", "Unknown sign-in provider.")
    web_final = _web_final()
    if client not in ("web", *MOBILE_CLIENTS):
        return _redirect(web_final, error="bad_request")
    mobile = client in MOBILE_CLIENTS
    final = web_final
    if mobile and redirect_uri:
        if redirect_uri not in _allowed_redirects():
            return _redirect(web_final, error="bad_request")
        final = redirect_uri
    provider = _provider(p)
    if not _configured(provider):
        return _redirect(final, error="provider_unavailable")
    if mobile and not (challenge and _CHALLENGE_RE.match(challenge)):
        return _redirect(final, error="bad_request")

    link_user_id = None
    if link:
        ticket = oauth_db.take_ticket("link", link, _now())
        if (
            not ticket
            or ticket["provider"] != p
            or not ticket["user_id"]
            or ticket["data"].get("client", "web") != client
        ):
            return _redirect(final, error="bad_request")
        # a web link ticket only works in the browser that asked for it (a
        # forwarded start_url must not attach someone else's identity); mobile
        # links are proven by the app's verifier at exchange
        if not mobile and not oauth_db.binding_matches(
            request.cookies.get(LINK_COOKIE), ticket["binding_hash"]
        ):
            return _redirect(final, error="bad_request")
        link_user_id = ticket["user_id"]
    target = _safe_return_to(return_to, "/account" if link_user_id else "/")
    if target is None:
        return _redirect(final, error="bad_request")

    try:
        verifier = pkce_verifier()
        nonce = secrets.token_urlsafe(32)
        binding = secrets.token_urlsafe(32)
        state = oauth_db.put_ticket(
            "state",
            ttl_s=STATE_TTL_S,
            provider=p,
            user_id=link_user_id,
            data={
                "client": client,
                "final": final,
                "return_to": target,
                "verifier": verifier,
                "nonce": nonce,
            },
            binding=binding,
            client_challenge=challenge if mobile else None,
        )
        url = provider.authorize_url(
            redirect_uri=_callback_uri(p),
            state=state,
            nonce=nonce,
            code_challenge=pkce_challenge(verifier),
        )
    except Exception:
        logger.exception("oauth.start_failed provider=%s", p)
        return _redirect(final, error="provider_unavailable")
    resp = RedirectResponse(url, status_code=302)
    # one binding per browser: a second concurrent start replaces it, and the
    # first flow then fails at exchange with code_invalid (start again)
    _set_binding_cookie(resp, COOKIE, binding, STATE_TTL_S)
    if link:
        resp.delete_cookie(LINK_COOKIE, path=COOKIE_PATH)
    return resp


async def _callback(p: str, request: Request) -> RedirectResponse:
    params: dict[str, str] = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            params.update({k: v for k, v in form.items() if isinstance(v, str)})
        except Exception:
            pass
    web_final = _web_final()
    if p not in registry.PROVIDER_ORDER:
        return _redirect(web_final, error="bad_request")
    state = oauth_db.take_ticket("state", params.get("state") or "", _now())
    if not state or state["provider"] != p:
        return _redirect(web_final, error="state_invalid")
    data = state["data"]
    final = data.get("final") or web_final
    if params.get("error"):
        code = "cancelled" if params["error"] in _CANCEL_ERRORS else "provider_error"
        return _redirect(final, error=code)
    if not params.get("code"):
        return _redirect(final, error="bad_request")
    provider = _provider(p)
    if not _configured(provider):
        return _redirect(final, error="provider_unavailable")
    try:
        profile, secret = await provider.exchange(
            code=params["code"],
            redirect_uri=_callback_uri(p),
            code_verifier=data["verifier"],
            nonce=data["nonce"],
            form=params,
        )
    except OAuthError as exc:
        logger.info("oauth.callback provider=%s result=%s", p, exc.code)
        return _redirect(final, error=exc.code)
    except Exception as exc:
        logger.warning("oauth.callback provider=%s error=%s", p, type(exc).__name__)
        return _redirect(final, error="provider_error")
    link_user_id = state["user_id"]
    try:
        if link_user_id:
            # pre-check only: the attach waits for the exchange's proof
            result = flow.precheck_link(profile, p, link_user_id) or "link"
        else:
            result = flow.resolve_identity(profile, p, link_user_id=None, secret=secret)
    except Exception:
        logger.exception("oauth.resolve_failed provider=%s", p)
        return _redirect(final, error="provider_error")
    if isinstance(result, flow.Refused):
        logger.info("oauth.callback provider=%s result=%s", p, result.code)
        return _redirect(final, error=result.code)
    handoff = {
        "client": data.get("client", "web"),
        "return_to": data.get("return_to", "/"),
        "provider": p,
    }
    if result == "link":
        handoff["result"] = "link"
        handoff["profile"] = flow.profile_to_dict(profile)
        handoff["secret_enc"] = seal(secret) if secret else None
        user_id = link_user_id
    elif isinstance(result, flow.NeedsUsername):
        handoff["result"] = "needs_username"
        handoff["pending"] = result.pending_data
        user_id = None
    else:
        handoff["result"] = "linked" if isinstance(result, flow.Linked) else "signed_in"
        user_id = result.user["id"]
    code = oauth_db.put_ticket(
        "handoff",
        ttl_s=HANDOFF_TTL_S,
        provider=p,
        user_id=user_id,
        data=handoff,
        binding_hash=state["binding_hash"],
        client_challenge=state["client_challenge"],
    )
    logger.info("oauth.callback provider=%s result=%s", p, handoff["result"])
    return _redirect(final, code=code)


@router.get("/auth/oauth/{p}/callback", dependencies=_oauth_limit)
async def callback_get(p: str, request: Request):
    return await _callback(p, request)


@router.post("/auth/oauth/{p}/callback", dependencies=_oauth_limit)
async def callback_post(p: str, request: Request):
    return await _callback(p, request)


# ── Results ──────────────────────────────────────────────────────────────────


def _needs_username(pending: dict, provider: str, return_to: str) -> dict:
    token = oauth_db.put_ticket(
        "signup",
        ttl_s=SIGNUP_TTL_S,
        provider=provider,
        data={**pending, "return_to": return_to},
    )
    return {
        "status": "needs_username",
        "signup_token": token,
        "suggested_username": flow.suggest_username(
            pending.get("email"), pending.get("display_name")
        ),
        "display_name": pending.get("display_name"),
        "email": pending.get("email"),
        "invite_required": settings.signup_mode == "invite",
        "return_to": return_to,
    }


def _signed_in(user: dict, client: str, device_name: str | None, return_to: str):
    if not user or not user.get("is_active") or user.get("account_status") != "active":
        return None
    return {
        "status": "signed_in",
        "session": issue_session(user, client, device_name),
        "game": _game(user["id"]),
        "return_to": return_to,
    }


class ExchangeRequest(BaseModel):
    code: str = Field(..., max_length=512)
    verifier: str | None = Field(None, max_length=128)
    device_name: str | None = Field(None, max_length=64)


@router.post("/auth/oauth/exchange", dependencies=_oauth_limit)
def exchange(req: ExchangeRequest, request: Request):
    from ...db.users_db import get_user_by_id

    ticket = oauth_db.take_ticket("handoff", req.code, _now())
    if not ticket:
        raise _code_invalid()
    data = ticket["data"]
    client = data.get("client", "web")
    if client in MOBILE_CLIENTS:
        want = ticket["client_challenge"] or ""
        if not req.verifier or not hmac.compare_digest(
            pkce_challenge(req.verifier), want
        ):
            raise _code_invalid()
    elif not oauth_db.binding_matches(
        request.cookies.get(COOKIE), ticket["binding_hash"]
    ):
        raise _code_invalid()
    return_to = data.get("return_to", "/")
    kind = data.get("result")
    if kind == "needs_username":
        body = _needs_username(data["pending"], ticket["provider"], return_to)
    elif kind == "link":
        try:
            linked = flow.resolve_identity(
                flow.profile_from_dict(data["profile"]),
                ticket["provider"],
                link_user_id=ticket["user_id"],
                secret=None,
                secret_enc=data.get("secret_enc"),
            )
        except Exception:
            logger.exception("oauth.link_failed provider=%s", ticket["provider"])
            raise _code_invalid() from None
        if isinstance(linked, flow.Refused):
            raise ApiError(
                _REFUSED_STATUS.get(linked.code, 409),
                linked.code,
                "This sign-in method can't be linked to your account.",
            )
        body = {
            "status": "linked",
            "provider": ticket["provider"],
            "return_to": return_to,
        }
    else:
        body = _signed_in(
            get_user_by_id(ticket["user_id"] or ""), client, req.device_name, return_to
        )
        if body is None:
            raise _code_invalid()
    resp = JSONResponse(body)
    if client not in MOBILE_CLIENTS:
        resp.delete_cookie(COOKIE, path=COOKIE_PATH)
    return resp


class CompleteRequest(BaseModel):
    signup_token: str = Field(..., max_length=512)
    username: str = Field(..., max_length=64)
    display_name: str | None = Field(None, max_length=200)
    invite_code: str | None = Field(None, max_length=64)
    client: Literal["web", "ios", "android"] = "web"
    device_name: str | None = Field(None, max_length=64)
    locale: str | None = Field(None, max_length=16)


def _signup_token_invalid() -> ApiError:
    return ApiError(
        400, "signup_token_invalid", "This sign-up has expired. Start again."
    )


def _provider_display_name(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return _display_name(raw[:50])
    except ApiError:
        return None


@router.post("/auth/oauth/complete", status_code=201, dependencies=_oauth_limit)
async def complete(req: CompleteRequest, background: BackgroundTasks):
    now = _now()
    if not oauth_db.peek_ticket("signup", req.signup_token, now):
        raise _signup_token_invalid()
    username = req.username.strip().lower()
    if not flow.USERNAME_RE.match(username):
        raise ApiError(
            422,
            "username_invalid",
            "Use 3–20 lowercase letters, digits or underscores.",
        )
    if username in flow.RESERVED_USERNAMES:
        raise ApiError(422, "username_reserved", "That username is reserved.")
    display_name = _display_name(req.display_name) if req.display_name else None
    invite = None
    if settings.signup_mode == "invite":
        if not req.invite_code:
            raise ApiError(403, "invite_required", "An invite code is required.")
        if invites_db.check_invite(req.invite_code) is None:
            raise ApiError(403, "invite_invalid", "That invite code is not valid.")
        invite = req.invite_code
    from ...db.users_db import username_available

    if not username_available(username, now):
        raise ApiError(409, "username_taken", "That username is taken.")

    ticket = oauth_db.take_ticket("signup", req.signup_token, now)
    if not ticket:
        raise _signup_token_invalid()
    pending = ticket["data"]
    # one transaction (invite use + user + identity): on any failure nothing
    # is kept, the invite is not used up and the token is released for a retry
    try:
        user = flow.create_oauth_user(
            pending,
            username=username,
            display_name=display_name
            or _provider_display_name(pending.get("display_name")),
            locale=_locale(req.locale),
            invite_code=invite,
        )
    except Exception as exc:
        oauth_db.release_ticket("signup", req.signup_token)
        logger.info("oauth.complete_failed reason=%s", type(exc).__name__)
        if isinstance(exc, flow.UsernameTaken):
            raise ApiError(409, "username_taken", "That username is taken.") from None
        if isinstance(exc, flow.InviteInvalid):
            raise ApiError(
                403, "invite_invalid", "That invite code is not valid."
            ) from None
        if not isinstance(exc, flow.EmailTaken | flow.IdentityTaken):
            logger.exception("oauth.complete_error")
        raise _signup_token_invalid() from None

    delta = None
    email = user.get("email")
    if email and user.get("email_verified"):
        delta = hooks.on_email_verified(user["id"])
    elif email:
        from ...services.account_email import send_account_email

        token = flow.issue_verify_token(user["id"], email)
        background.add_task(
            send_account_email,
            "verify",
            email,
            link=public_url(f"/verify?token={token}"),
            locale=user.get("locale"),
            username=user["username"],
        )
    if pending.get("picture_url"):
        from ...services.avatar import import_provider_photo

        background.add_task(import_provider_photo, user["id"], pending["picture_url"])
    logger.info("oauth.complete provider=%s", pending.get("provider"))
    return {
        "status": "signed_in",
        "session": issue_session(user, req.client, req.device_name),
        "game": _game(user["id"], delta),
    }


# ── Linking ──────────────────────────────────────────────────────────────────


class LinkTicketRequest(BaseModel):
    provider: str = Field(..., max_length=32)
    client: Literal["web", "ios", "android"] = "web"


@router.post("/auth/oauth/link-ticket", dependencies=_oauth_limit)
def link_ticket(req: LinkTicketRequest, user: dict = Depends(get_current_user)):
    p = req.provider
    if p not in registry.PROVIDER_ORDER:
        raise ApiError(404, "provider_unknown", "Unknown sign-in provider.")
    if not _configured(_provider(p)):
        raise ApiError(
            409, "provider_unavailable", "That sign-in method isn't available yet."
        )
    binding = secrets.token_urlsafe(32) if req.client == "web" else None
    ticket = oauth_db.put_ticket(
        "link",
        ttl_s=LINK_TTL_S,
        provider=p,
        user_id=user["id"],
        data={"client": req.client},
        binding=binding,
    )
    query = urlencode({"link": ticket, "client": req.client})
    resp = JSONResponse({"start_url": f"/api/auth/oauth/{p}/start?{query}"})
    if binding:
        # same-origin XHR: the browser keeps it and sends it with the start
        _set_binding_cookie(resp, LINK_COOKIE, binding, LINK_TTL_S)
    return resp


# ── Native ID tokens (Apple, Google) ─────────────────────────────────────────


class IdTokenRequest(BaseModel):
    id_token: str = Field(..., max_length=8192)
    nonce: str | None = Field(None, max_length=256)
    authorization_code: str | None = Field(None, max_length=2048)
    display_name: str | None = Field(None, max_length=200)
    client: Literal["ios", "android"]
    device_name: str | None = Field(None, max_length=64)


_REFUSED_STATUS = {"account_inactive": 403}


@router.post("/auth/oauth/{p}/id-token", dependencies=_oauth_limit)
async def id_token(p: str, req: IdTokenRequest):
    provider = _provider(p)
    if not _native(p, provider):
        raise ApiError(404, "provider_unknown", "Native sign-in is not available.")
    try:
        native = getattr(provider, "verify_native", None)
        if callable(native):
            profile, secret = await native(
                req.id_token,
                nonce=req.nonce,
                authorization_code=req.authorization_code,
                display_name=req.display_name,
            )
        else:
            profile = await provider.verify_id_token(req.id_token, nonce=req.nonce)
            secret = None
    except Exception as exc:
        logger.info("oauth.id_token provider=%s error=%s", p, type(exc).__name__)
        raise ApiError(
            400, "id_token_invalid", "The sign-in token could not be verified."
        ) from None
    if req.display_name and not profile.display_name:
        profile = dataclasses.replace(profile, display_name=req.display_name)
    try:
        result = flow.resolve_identity(profile, p, link_user_id=None, secret=secret)
        if isinstance(result, flow.NeedsUsername):
            return _needs_username(result.pending_data, p, "/")
    except Exception as exc:
        logger.warning("oauth.id_token provider=%s error=%s", p, type(exc).__name__)
        raise ApiError(
            400, "provider_error", "Sign-in failed. Please try again."
        ) from None
    if isinstance(result, flow.Refused):
        raise ApiError(
            _REFUSED_STATUS.get(result.code, 409),
            result.code,
            "This sign-in can't be used for an account right now.",
        )
    body = _signed_in(result.user, req.client, req.device_name, "/")
    if body is None:
        raise ApiError(403, "account_inactive", "This account is not active.")
    return body
