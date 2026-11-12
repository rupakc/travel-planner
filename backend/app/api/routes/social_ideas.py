"""Social ideas feed, comments and reports (Phase 5). Contract:
docs/Social-API.md. Same flag and buckets as ``social.py``."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...core.config import settings
from ...core.errors import ApiError
from ...core.rate_limit import rate_limit
from ...core.session_payload import user_payload
from ...db import plans_db, preferences_db, social_db
from ...db import social_ideas_db as db
from ...game import engine
from ...services import idea_snapshot, moderation
from .social import _avatar, _need_profile, _target, require_enabled

logger = logging.getLogger(__name__)

IDEA_DAILY_CAP = 5
COMMENT_DAILY_CAP = 30
REPORT_DAILY_CAP = 20
AUTO_HIDE_REPORTERS = 3
TITLE_MAX, CAPTION_MAX, COMMENT_MAX, NOTE_MAX = 80, 500, 300, 200

reads = APIRouter(dependencies=[Depends(rate_limit("social_read"))])
writes = APIRouter(dependencies=[Depends(rate_limit("social_write"))])
router = APIRouter(dependencies=[Depends(require_enabled)])


def _verified(user: dict) -> bool:
    return user_payload(user)["account_verified"]


def _writer(user: dict) -> dict:
    """Guard for posting and commenting: a non-private profile, a verified
    account, no restriction. Returns the profile."""
    p = _need_profile(user)
    if p["visibility"] == "private":
        raise ApiError(403, "profile_required", "Make your profile visible first.")
    if not _verified(user):
        raise ApiError(403, "email_unverified", "Confirm your email first.")
    if db.is_restricted(user["id"]):
        raise ApiError(403, "restricted", "Your account is restricted for now.")
    return p


def _limit(user: dict, kind: str, cap: int) -> None:
    if not social_db.consume_daily(user["id"], kind, cap):
        raise ApiError(422, "limit_reached", "Daily limit reached.")


def _cursor(cursor: str | None) -> int | None:
    try:
        return int(cursor) if cursor else None
    except ValueError:
        raise ApiError(422, "invalid_cursor", "Bad cursor.") from None


def _award(user_id: str, rule: str, key: str) -> None:
    """XP for a social event; never breaks the request."""
    if not settings.game_enabled:
        return
    try:
        engine.award(user_id, rule, key)
    except Exception:
        logger.exception("game award failed (rule=%s)", rule)


def _out(i: dict) -> dict:
    author = {"handle": i["author_handle"]}
    if i["author_show_avatar"] and (url := _avatar(i["author_id"])):
        author["avatar_url"] = url
    return {
        "id": i["id"],
        "kind": i["kind"],
        "title": i["title"],
        "caption": i["caption"],
        "author": author,
        "snapshot": i["snapshot"],
        "likes": i["likes"],
        "saves": i["saves"],
        "comments": i["comments"],
        "liked": i["liked"],
        "saved": i["saved"],
        "mine": i["mine"],
        "status": i["status"],
        "created_at": i["created_at"],
    }


def _visible(user: dict, idea_id: int, *, published: bool = False) -> dict:
    idea = db.get_idea(idea_id, user["id"], admin=bool(user.get("is_admin")))
    if not idea or (published and idea["status"] != "published"):
        raise ApiError(404, "idea_not_found", "Idea not found.")
    return idea


# ── ideas ─────────────────────────────────────────────────────────────────────


class IdeaBody(BaseModel):
    plan_id: int
    kind: Literal["plan", "recap"]
    title: str = Field(..., max_length=TITLE_MAX)
    caption: str = Field("", max_length=CAPTION_MAX)
    locale: str | None = Field(None, max_length=8)


@writes.post("/social/ideas")
def publish_idea(body: IdeaBody, user: dict = Depends(get_current_user)):
    _writer(user)
    plan = plans_db.get_plan(body.plan_id)
    if not plan or plan["username"] != user["username"]:
        raise ApiError(404, "plan_not_found", "Plan not found.")
    title = moderation.plain_text(body.title, TITLE_MAX)
    caption = moderation.plain_text(body.caption, CAPTION_MAX)
    if not title:
        raise ApiError(422, "title_invalid", "Give the idea a title.")
    verdict = moderation.verdict(title, caption)
    if verdict == "reject":
        raise ApiError(422, "content_rejected", "That text can't be used.")
    snap = idea_snapshot.build(plan, body.kind)
    if len(str(snap).encode()) > idea_snapshot.SNAPSHOT_MAX_BYTES:
        raise ApiError(422, "snapshot_too_large", "That plan is too large to share.")
    existing = db.find_idea(user["id"], body.plan_id, body.kind)
    if existing and existing["status"] in ("hidden", "removed"):
        raise ApiError(403, "idea_unavailable", "This idea was taken down.")
    if not existing:
        _limit(user, "idea", IDEA_DAILY_CAP)
    idea_id = db.upsert_idea(
        user["id"],
        body.plan_id,
        body.kind,
        title,
        caption,
        snap,
        snap["interests"],
        # A held idea stays held (until an admin approves) however it is edited.
        "held"
        if (verdict == "review" or (existing and existing["status"] == "held"))
        else "published",
    )
    return _out(db.get_idea(idea_id, user["id"]))


@reads.get("/social/feed")
def feed(
    scope: Literal["for_you", "following", "new"] = "for_you",
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=30),
    user: dict = Depends(get_current_user),
):
    interests = (
        preferences_db.get_preferences(user["username"]).get("interests")
        if scope == "for_you"
        else None
    )
    ideas, nxt = db.feed(
        user["id"], scope, cursor=_cursor(cursor), limit=limit, interests=interests
    )
    return {"ideas": [_out(i) for i in ideas], "next": str(nxt) if nxt else None}


@reads.get("/social/ideas/{idea_id}")
def get_idea(idea_id: int, user: dict = Depends(get_current_user)):
    return _out(_visible(user, idea_id))


@writes.delete("/social/ideas/{idea_id}", status_code=204)
def delete_idea(idea_id: int, user: dict = Depends(get_current_user)):
    raw = db.get_idea_raw(idea_id)
    if not raw or raw["author_id"] != user["id"]:
        raise ApiError(404, "idea_not_found", "Idea not found.")
    db.delete_idea(idea_id)
    return Response(status_code=204)


@reads.get("/social/profile/{handle}/ideas")
def profile_ideas(
    handle: str,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=30),
    user: dict = Depends(get_current_user),
):
    p = _target(user, handle, visible=True)
    ideas, nxt = db.profile_ideas(
        user["id"], p["user_id"], cursor=_cursor(cursor), limit=limit
    )
    return {"ideas": [_out(i) for i in ideas], "next": str(nxt) if nxt else None}


# ── likes and saves ───────────────────────────────────────────────────────────


@writes.put("/social/ideas/{idea_id}/like", status_code=204)
def like(idea_id: int, user: dict = Depends(get_current_user)):
    _visible(user, idea_id, published=True)
    db.set_like(idea_id, user["id"], True)
    return Response(status_code=204)


@writes.delete("/social/ideas/{idea_id}/like", status_code=204)
def unlike(idea_id: int, user: dict = Depends(get_current_user)):
    db.set_like(idea_id, user["id"], False)
    return Response(status_code=204)


@writes.post("/social/ideas/{idea_id}/save")
def save(idea_id: int, user: dict = Depends(get_current_user)):
    idea = _visible(user, idea_id, published=True)
    prior = db.get_save(idea_id, user["id"])
    if prior and prior["plan_id"] and plans_db.get_plan(prior["plan_id"]):
        return {"plan_id": prior["plan_id"]}
    name, search, selections = idea_snapshot.to_plan(
        idea["title"], idea["snapshot"], idea_id, idea["author_handle"]
    )
    plan = plans_db.save_plan(user["username"], name, search, selections)
    db.put_save(idea_id, user["id"], plan["id"])
    if idea["author_id"] != user["id"] and _verified(user):
        _award(idea["author_id"], "idea_saved", f"idea_saved:{user['id']}:{idea_id}")
    return {"plan_id": plan["id"]}


@writes.delete("/social/ideas/{idea_id}/save", status_code=204)
def unsave(idea_id: int, user: dict = Depends(get_current_user)):
    db.delete_save(idea_id, user["id"])
    return Response(status_code=204)


# ── comments ──────────────────────────────────────────────────────────────────


def _comment_out(c: dict) -> dict:
    return {
        "id": c["id"],
        "author": {"handle": c["author_handle"]},
        "text": c["text"],
        "helpful": c["helpful"],
        "mine": c["mine"],
        "status": c["status"],
        "created_at": c["created_at"],
    }


@reads.get("/social/ideas/{idea_id}/comments")
def list_comments(
    idea_id: int,
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=50),
    user: dict = Depends(get_current_user),
):
    _visible(user, idea_id)
    rows, nxt = db.list_comments(
        idea_id,
        user["id"],
        admin=bool(user.get("is_admin")),
        cursor=_cursor(cursor),
        limit=limit,
    )
    return {
        "comments": [_comment_out(c) for c in rows],
        "next": str(nxt) if nxt else None,
    }


class CommentBody(BaseModel):
    text: str = Field(..., max_length=COMMENT_MAX)


@writes.post("/social/ideas/{idea_id}/comments")
def add_comment(
    idea_id: int, body: CommentBody, user: dict = Depends(get_current_user)
):
    me = _writer(user)
    _visible(user, idea_id, published=True)
    text = moderation.plain_text(body.text, COMMENT_MAX)
    if not text:
        raise ApiError(422, "text_invalid", "Write a comment first.")
    verdict = moderation.verdict(text)
    if verdict == "reject":
        raise ApiError(422, "content_rejected", "That text can't be used.")
    _limit(user, "comment", COMMENT_DAILY_CAP)
    cid = db.add_comment(
        idea_id, user["id"], text, "held" if verdict == "review" else "published"
    )
    c = db.get_comment(cid)
    return _comment_out(
        {**c, "author_handle": me["handle"], "mine": True, "helpful": False}
    )


def _comment_for(user: dict, comment_id: int) -> tuple[dict, dict]:
    c = db.get_comment(comment_id)
    idea = (
        db.get_idea(c["idea_id"], user["id"], admin=bool(user.get("is_admin")))
        if c
        else None
    )
    if not c or not idea:
        raise ApiError(404, "comment_not_found", "Comment not found.")
    return c, idea


@writes.delete("/social/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: int, user: dict = Depends(get_current_user)):
    c, idea = _comment_for(user, comment_id)
    if user["id"] not in (c["author_id"], idea["author_id"]):
        raise ApiError(404, "comment_not_found", "Comment not found.")
    db.delete_comment(comment_id)
    return Response(status_code=204)


def _mark_helpful(comment_id: int, user: dict, on: bool) -> Response:
    c, idea = _comment_for(user, comment_id)
    if idea["author_id"] != user["id"] or c["status"] != "published":
        raise ApiError(404, "comment_not_found", "Comment not found.")
    db.set_helpful(comment_id, on)
    if on and c["author_id"] != user["id"]:
        _award(c["author_id"], "comment_helpful", f"comment_helpful:{comment_id}")
    return Response(status_code=204)


@writes.put("/social/comments/{comment_id}/helpful", status_code=204)
def helpful(comment_id: int, user: dict = Depends(get_current_user)):
    return _mark_helpful(comment_id, user, True)


@writes.delete("/social/comments/{comment_id}/helpful", status_code=204)
def not_helpful(comment_id: int, user: dict = Depends(get_current_user)):
    return _mark_helpful(comment_id, user, False)


# ── reports ───────────────────────────────────────────────────────────────────


class ReportBody(BaseModel):
    target: Literal["idea", "comment", "profile"]
    id: str = Field(..., max_length=40)
    reason: Literal["spam", "abuse", "sexual", "violence", "misinformation", "other"]
    note: str | None = Field(None, max_length=NOTE_MAX)


def _report_target(user: dict, body: ReportBody) -> tuple[str, str, str, str | None]:
    """``(target, stored id, owner user id, status)`` or 404."""
    nf = ApiError(404, "not_found", "Nothing to report.")
    if body.target == "profile":
        p = _target(user, body.id, visible=True)
        return "profile", p["user_id"], p["user_id"], None
    if not body.id.isdigit():
        raise nf
    n = int(body.id)
    if body.target == "idea":
        idea = db.get_idea(n, user["id"])
        if not idea:
            raise nf
        return "idea", str(n), idea["author_id"], idea["status"]
    c = db.get_comment(n)
    idea = db.get_idea(c["idea_id"], user["id"]) if c else None
    if not c or not idea:
        raise nf
    return "comment", str(n), c["author_id"], c["status"]


@writes.post("/social/reports", status_code=204)
def report(body: ReportBody, user: dict = Depends(get_current_user)):
    target, tid, owner, status = _report_target(user, body)
    _limit(user, "report", REPORT_DAILY_CAP)
    note = moderation.plain_text(body.note or "", NOTE_MAX)
    counted = _verified(user) and owner != user["id"]
    if db.add_report(user["id"], target, tid, body.reason, note, counted) and (
        counted
        and target != "profile"
        and status == "published"
        and db.counted_reporters(target, tid) >= AUTO_HIDE_REPORTERS
    ):
        db.set_status("ideas" if target == "idea" else "comments", int(tid), "hidden")
    return Response(status_code=204)


router.include_router(reads)
router.include_router(writes)
