"""Asynchronous head-to-head. A match is two ``quiz_sessions`` over the same
questions (the creator's and the opponent's); scores are read from them, and
the opponent's score stays hidden until both have finished. No AI call."""

import logging
import secrets
from datetime import datetime

from ..core.errors import ApiError
from ..db import game_db, play_db, quiz_db, social_db
from ..db.database import get_connection
from ..game import engine as game_engine
from ..game.quiz import engine as quiz_engine
from ..game.quiz import service as quiz_service

logger = logging.getLogger(__name__)

TTL_MS = 48 * 3600 * 1000
MAX_OPEN = 5
MAX_PER_DAY = 10
DAY_MS = 86_400_000


def _not_found() -> ApiError:
    return ApiError(404, "match_not_found", "Match not found.")


def _finished(conn, sid: str | None) -> dict | None:
    if not sid:
        return None
    s = quiz_db.get_session(conn, sid)
    return s if s and s["finished_ms"] is not None else None


def _handle(user_id: str) -> str | None:
    p = social_db.get_profile(user_id)
    return p["handle"] if p else None


def create(user_id: str, handle: str, pack: str) -> dict:
    if pack not in quiz_engine.PACKS:
        raise ApiError(422, "invalid_pack", "Unknown pack.")
    opp = social_db.get_profile_by_handle(handle)
    if (
        not opp
        or opp["visibility"] == "private"
        or social_db.is_blocked_either_way(user_id, opp["user_id"])
        or game_db.hide_game(opp["user_id"])
    ):
        raise ApiError(404, "profile_not_found", "Profile not found.")
    if opp["user_id"] == user_id:
        raise ApiError(422, "cannot_challenge_self", "You cannot challenge yourself.")
    now = quiz_service._now_ms()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        day_start = now - now % DAY_MS
        if (
            play_db.count_open_created(conn, user_id, now) >= MAX_OPEN
            or play_db.count_created_since(conn, user_id, day_start) >= MAX_PER_DAY
        ):
            raise ApiError(422, "limit_reached", "Too many head-to-head matches.")
        seed = secrets.token_hex(8)
        questions = quiz_engine.build_questions(pack, seed)
        sid, mid = secrets.token_urlsafe(12), secrets.token_urlsafe(9)
        quiz_db.create_session(
            conn,
            sid,
            user_id,
            "h2h",
            pack,
            quiz_service._today(now),
            seed,
            questions,
            now,
        )
        play_db.create_match(
            conn, mid, user_id, opp["user_id"], pack, seed, sid, now, TTL_MS
        )
        view = quiz_service.view(
            quiz_db.get_session(conn, sid), quiz_db.answers(conn, sid)
        )
    return {"id": mid, **view}


def _entry(conn, m: dict, user_id: str, now: int) -> dict:
    mine_creator = m["creator_id"] == user_id
    my_sid = m["creator_session_id"] if mine_creator else m["opponent_session_id"]
    their_sid = m["opponent_session_id"] if mine_creator else m["creator_session_id"]
    mine, theirs = _finished(conn, my_sid), _finished(conn, their_sid)
    both = bool(mine and theirs)
    if m["declined"]:
        state = "declined"
    elif both:
        state = "done"
    elif now > m["expires_ms"]:
        state = "expired"
    elif mine:
        state = "waiting_them"
    else:
        state = "waiting_you"
    winner = None
    if both:
        a, b = mine["score"], theirs["score"]
        winner = "you" if a > b else "them" if b > a else "draw"
    return {
        "id": m["id"],
        "opponent": {
            "handle": _handle(m["opponent_id"] if mine_creator else m["creator_id"])
        },
        "pack": m["pack"],
        "state": state,
        "you": mine["score"] if mine else None,
        "them": theirs["score"] if both else None,
        "winner": winner,
        "expires_at": quiz_service._iso(m["expires_ms"]),
        "session_id": my_sid,
    }


def _visible(user_id: str, m: dict) -> bool:
    other = m["opponent_id"] if m["creator_id"] == user_id else m["creator_id"]
    return not social_db.is_blocked_either_way(user_id, other)


def list_matches(user_id: str) -> list[dict]:
    return list_matches_at(user_id, quiz_service._now_ms())


def waiting_for_you(user_id: str, now: int) -> int:
    return sum(1 for e in list_matches_at(user_id, now) if e["state"] == "waiting_you")


def list_matches_at(user_id: str, now: int) -> list[dict]:
    with get_connection() as conn:
        rows = play_db.list_for_user(conn, user_id)
        return [_entry(conn, m, user_id, now) for m in rows if _visible(user_id, m)]


def _mine(conn, mid: str, user_id: str) -> dict:
    m = play_db.get_match(conn, mid)
    if (
        not m
        or user_id not in (m["creator_id"], m["opponent_id"])
        or not _visible(user_id, m)
    ):
        raise _not_found()
    return m


def accept(user_id: str, mid: str) -> dict:
    now = quiz_service._now_ms()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        m = _mine(conn, mid, user_id)
        if m["opponent_id"] != user_id:
            raise _not_found()
        if m["declined"]:
            raise ApiError(409, "invalid_state", "This match was declined.")
        if m["opponent_session_id"]:
            sid = m["opponent_session_id"]
            resumed = True
        else:
            if now > m["expires_ms"]:
                raise ApiError(410, "match_expired", "This match has expired.")
            creator = quiz_db.get_session(conn, m["creator_session_id"])
            sid, resumed = secrets.token_urlsafe(12), False
            quiz_db.create_session(
                conn,
                sid,
                user_id,
                "h2h",
                m["pack"],
                quiz_service._today(now),
                m["seed"],
                creator["questions"],
                now,
            )
            play_db.set_opponent_session(conn, mid, sid)
    if resumed:
        return {"id": mid, **quiz_service.get(user_id, sid), "resumed": True}
    with get_connection() as conn:
        view = quiz_service.view(
            quiz_db.get_session(conn, sid), quiz_db.answers(conn, sid)
        )
    return {"id": mid, **view}


def decline(user_id: str, mid: str) -> None:
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        m = _mine(conn, mid, user_id)
        if m["opponent_id"] != user_id:
            raise _not_found()
        if m["opponent_session_id"] or m["declined"]:
            raise ApiError(
                409, "invalid_state", "This match can no longer be declined."
            )
        play_db.decline(conn, mid)


def on_finished(s: dict, at: datetime) -> dict | None:
    """Called when a h2h quiz session finishes. When both sides are done each
    gets ``h2h_complete`` XP (idempotent per match and user); returns this
    session's XP summary, or None while the match is still open."""
    with get_connection() as conn:
        m = play_db.match_for_session(conn, s["id"])
        if not m:
            return None
        other_sid = (
            m["opponent_session_id"]
            if s["id"] == m["creator_session_id"]
            else m["creator_session_id"]
        )
        other = _finished(conn, other_sid)
    if not other:
        return None
    own = game_engine.award(
        s["user_id"], "h2h_complete", f"h2h_complete:{m['id']}:{s['user_id']}", now=at
    )
    theirs = game_engine.award(
        other["user_id"],
        "h2h_complete",
        f"h2h_complete:{m['id']}:{other['user_id']}",
        now=at,
    )
    with get_connection() as conn:
        quiz_db.save_rewards(conn, other["id"], theirs, other.get("streak"))
    return own
