"""Social (Phase 5): profiles, follows and blocks. Contract: docs/Social-API.md.

Every route needs sign-in and answers 404 ``social_disabled`` while
``SOCIAL_ENABLED`` is off. Reads use the ``social_read`` bucket, writes the
``social_write`` bucket (router dependencies, so this module's routers are
included once in main.py).
"""

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...core.config import settings
from ...core.errors import ApiError
from ...core.rate_limit import rate_limit
from ...core.session_payload import _avatar_url
from ...db import game_db, social_db, user_countries_db, users_db
from ...game import engine
from ...game.engine import get_rules
from ...services import moderation, social_profile

FOLLOW_DAILY_CAP = 200


def require_enabled() -> None:
    if not settings.social_enabled:
        raise ApiError(404, "social_disabled", "Not found")


_ON = [Depends(require_enabled)]
reads = APIRouter(dependencies=[Depends(rate_limit("social_read"))])
writes = APIRouter(dependencies=[Depends(rate_limit("social_write"))])
router = APIRouter(dependencies=_ON)


def _not_found() -> ApiError:
    return ApiError(404, "profile_not_found", "Profile not found.")


def _me(user: dict) -> dict | None:
    return social_db.get_profile(user["id"])


def _need_profile(user: dict) -> dict:
    p = _me(user)
    if not p:
        raise ApiError(403, "profile_required", "Create a profile first.")
    return p


def _target(user: dict, handle: str, *, visible: bool) -> dict:
    """The profile behind ``handle``. ``visible``: apply the viewer rules
    (private or blocked either way -> 404)."""
    p = social_db.get_profile_by_handle(handle)
    if not p:
        raise _not_found()
    if p["user_id"] == user["id"]:
        return p
    if visible and not social_profile.can_view(
        p, blocked=social_db.is_blocked_either_way(user["id"], p["user_id"]), own=False
    ):
        raise _not_found()
    return p


# ── profile ───────────────────────────────────────────────────────────────────


@reads.get("/social/profile")
def get_own_profile(user: dict = Depends(get_current_user)):
    return social_profile.own_view(_me(user))


class ProfileBody(BaseModel):
    handle: str | None = Field(None, max_length=40)
    visibility: Literal["private", "followers", "public"] | None = None
    bio: str | None = Field(None, max_length=160)
    show_avatar: bool | None = None
    show_home_country: bool | None = None
    show_countries: bool | None = None
    show_level: bool | None = None
    show_badges: bool | None = None
    leaderboard_opt_in: bool | None = None
    home_country: str | None = Field(None, max_length=2)


_FLAG_FIELDS = (
    "visibility",
    "show_avatar",
    "show_home_country",
    "show_countries",
    "show_level",
    "show_badges",
    "leaderboard_opt_in",
)


@writes.put("/social/profile")
def put_profile(body: ProfileBody, user: dict = Depends(get_current_user)):
    current = _me(user)
    sent = body.model_fields_set
    fields: dict = {}

    if "handle" in sent and body.handle is not None:
        new = body.handle.strip().lower()
        if not current or new != current["handle_lower"]:
            if problem := social_profile.handle_problem(new):
                raise ApiError(
                    422, f"handle_{problem}", f"That handle is {problem}.", handle=new
                )
            if current and (wait := social_profile.handle_change_wait(current)):
                raise ApiError(
                    422,
                    "handle_rate_limited",
                    "A handle can change once every 30 days.",
                    retry_after=wait,
                )
            other = social_db.get_profile_by_handle(new)
            if other and other["user_id"] != user["id"]:
                raise ApiError(409, "handle_taken", "That handle is taken.")
            fields["handle"] = new
            if current:
                fields["handle_changed_at"] = social_db.now_iso()
    if not current and "handle" not in fields:
        raise ApiError(422, "handle_invalid", "Pick a handle to create a profile.")

    for k in _FLAG_FIELDS:
        v = getattr(body, k)
        if k in sent and v is not None:
            fields[k] = v
    if "bio" in sent and body.bio is not None:
        bio = moderation.plain_text(body.bio, social_profile.BIO_MAX)
        if moderation.check(bio) != "allow":
            raise ApiError(422, "content_rejected", "That text can't be used.")
        fields["bio"] = bio
    if "home_country" in sent:
        hc = (body.home_country or "").strip().upper()
        if hc and not social_profile.valid_country(hc):
            raise ApiError(422, "country_invalid", "Unknown country code.")
        fields["home_country"] = hc or None

    if fields:
        try:
            current = social_db.save_profile(user["id"], fields)
        except sqlite3.IntegrityError:  # lost a race for the handle
            raise ApiError(409, "handle_taken", "That handle is taken.") from None
    return social_profile.own_view(current)


@reads.get("/social/handles/check")
def check_handle(
    handle: str = Query("", max_length=40), user: dict = Depends(get_current_user)
):
    h = handle.strip().lower()
    if problem := social_profile.handle_problem(h):
        return {"available": False, "reason": problem}
    owner = social_db.handle_owner(h)
    if owner and owner != user["id"]:
        return {"available": False, "reason": "taken"}
    return {"available": True}


def _game_fields(user_id: str) -> dict:
    s = engine.summary(user_id, hidden=False)
    tiers = get_rules().badges
    return {
        "level": s["level"],
        "badges": [
            {"id": b["id"], "tier": tiers[b["id"]].tier}
            for b in s["badges"]
            if b["earned_at"] and b["id"] in tiers
        ],
    }


def _avatar(user_id: str) -> str | None:
    u = users_db.get_user_by_id(user_id)
    return _avatar_url(u) if u else None


@reads.get("/social/profile/{handle}")
def get_profile(handle: str, user: dict = Depends(get_current_user)):
    p = _target(user, handle, visible=True)
    uid, me = p["user_id"], user["id"]
    own = uid == me
    state = None if own else social_db.follow_state(me, uid)
    back = None if own else social_db.follow_state(uid, me)
    hidden = game_db.hide_game(uid) or not settings.game_enabled
    return social_profile.project(
        p,
        own=own,
        following=state == "following",
        hidden_game=hidden,
        counts={
            "ideas_count": social_db.ideas_count(uid),
            "followers_count": social_db.count_followers(uid),
            "following_count": social_db.count_following(uid),
        },
        you={
            "following": state == "following",
            "pending": state == "pending",
            "follows_you": back == "following",
            "blocked": False,  # a blocked pair gets 404 above
        },
        avatar=lambda: _avatar(uid),
        countries=lambda: sorted(
            {c["country_code"] for c in user_countries_db.list_countries(uid)}
        ),
        game=lambda: _game_fields(uid),
    )


# ── follow ────────────────────────────────────────────────────────────────────


@writes.put("/social/follow/{handle}")
def follow(handle: str, user: dict = Depends(get_current_user)):
    _need_profile(user)
    p = social_db.get_profile_by_handle(handle)
    if p and p["user_id"] == user["id"]:
        raise ApiError(422, "cannot_follow_self", "You can't follow yourself.")
    p = _target(user, handle, visible=True)
    existing = social_db.follow_state(user["id"], p["user_id"])
    if existing == "following":
        return {"state": "following"}
    if existing is None and not social_db.consume_daily(
        user["id"], "follow", FOLLOW_DAILY_CAP
    ):
        raise ApiError(422, "limit_reached", "Daily follow limit reached.")
    state = "following" if p["visibility"] == "public" else "pending"
    social_db.set_follow(user["id"], p["user_id"], state)
    return {"state": state}


@writes.delete("/social/follow/{handle}", status_code=204)
def unfollow(handle: str, user: dict = Depends(get_current_user)):
    p = _target(user, handle, visible=False)
    social_db.delete_follow(user["id"], p["user_id"])
    return Response(status_code=204)


@reads.get("/social/follow-requests")
def follow_requests(user: dict = Depends(get_current_user)):
    return {"requests": social_db.list_requests(user["id"])}


def _pending_from(user: dict, handle: str) -> dict:
    p = social_db.get_profile_by_handle(handle)
    if not p or social_db.follow_state(p["user_id"], user["id"]) != "pending":
        raise ApiError(404, "request_not_found", "No such follow request.")
    return p


@writes.post("/social/follow-requests/{handle}/accept", status_code=204)
def accept_request(handle: str, user: dict = Depends(get_current_user)):
    p = _pending_from(user, handle)
    social_db.set_follow(p["user_id"], user["id"], "following")
    return Response(status_code=204)


@writes.post("/social/follow-requests/{handle}/decline", status_code=204)
def decline_request(handle: str, user: dict = Depends(get_current_user)):
    p = _pending_from(user, handle)
    social_db.delete_follow(p["user_id"], user["id"])
    return Response(status_code=204)


def _edges(direction: str, user: dict, cursor: str | None, limit: int):
    try:
        cur = int(cursor) if cursor else None
    except ValueError:
        raise ApiError(422, "invalid_cursor", "Bad cursor.") from None
    users, nxt = social_db.list_follow_edges(user["id"], direction, cur, limit)
    return {"users": users, "next": str(nxt) if nxt is not None else None}


@reads.get("/social/following")
def following(
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    return _edges("following", user, cursor, limit)


@reads.get("/social/followers")
def followers(
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    return _edges("followers", user, cursor, limit)


# ── block ─────────────────────────────────────────────────────────────────────


@writes.put("/social/block/{handle}", status_code=204)
def block(handle: str, user: dict = Depends(get_current_user)):
    p = _target(user, handle, visible=False)
    if p["user_id"] == user["id"]:
        raise ApiError(422, "cannot_block_self", "You can't block yourself.")
    social_db.block(user["id"], p["user_id"])
    return Response(status_code=204)


@writes.delete("/social/block/{handle}", status_code=204)
def unblock(handle: str, user: dict = Depends(get_current_user)):
    p = _target(user, handle, visible=False)
    social_db.unblock(user["id"], p["user_id"])
    return Response(status_code=204)


@reads.get("/social/blocks")
def blocks(user: dict = Depends(get_current_user)):
    return {"users": [{"handle": h} for h in social_db.list_blocks(user["id"])]}


# include last: FastAPI copies a router's routes when it is included. The flag
# dependency sits on ``router`` so it runs before the bucket and sign-in.
router.include_router(reads)
router.include_router(writes)
