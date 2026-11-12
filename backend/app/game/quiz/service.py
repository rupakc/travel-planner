"""Quiz sessions: start/resume, server-timed answers, rewards. Orchestrates
``quiz_db`` and the pure ``engine``; the route stays thin. No AI call."""

import logging
import secrets
import time
from datetime import UTC, date, datetime

from ...core.errors import ApiError
from ...db import game_db, quiz_db
from ...db.database import get_connection
from ...services import challenge as challenge_svc
from .. import engine as game_engine
from . import engine as quiz_engine

logger = logging.getLogger(__name__)

SESSION_TTL_MS = 20 * 60 * 1000


def _now_ms() -> int:  # patched in tests
    return int(time.time() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()


def _answered(rows: list[dict]) -> list[dict]:
    return [a for a in rows if a["answered_ms"] is not None]


def _expired(s: dict, rows: list[dict], now: int) -> bool:
    """Idle for 20 minutes with at least one answer given. A session nobody
    has answered in yet reveals nothing, so it is simply resumed (its slow
    first answer just earns no speed bonus)."""
    return (
        s["finished_ms"] is None
        and now - s["updated_ms"] > SESSION_TTL_MS
        and bool(_answered(rows))
    )


def _finalize_expired(sid: str, now: int) -> None:
    """A session idle for 20 minutes ends as it stands: unanswered questions
    score nothing and no XP is awarded. Closing it keeps the daily quiz from
    being retried after its answers were revealed."""
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        s = quiz_db.get_session(conn, sid)
        if not s or s["finished_ms"] is not None:
            return
        rows = _answered(quiz_db.answers(conn, sid))
        quiz_db.finish(
            conn,
            sid,
            sum(a["points"] or 0 for a in rows),
            sum(1 for a in rows if a["correct"]),
            now,
        )
        quiz_db.save_rewards(conn, sid, None, None)


def view(s: dict, answers: list[dict], *, resumed: bool = False) -> dict:
    done = s["finished_ms"] is not None
    qs = s["questions"]
    out = {
        "session_id": s["id"],
        "mode": s["mode"],
        "pack": s["pack"],
        "questions": [quiz_engine.public(q) for q in qs],
        "expires_at": _iso(s["updated_ms"] + SESSION_TTL_MS),
        "answers": [
            {
                "index": a["idx"],
                "choice": a["choice"],
                "correct": bool(a["correct"]),
                "correct_choice": qs[a["idx"]]["answer"],
                "points": a["points"],
                "elapsed_ms": a["elapsed_ms"],
            }
            for a in answers
            if a["answered_ms"] is not None
        ],
        "done": done,
    }
    if resumed:
        out["resumed"] = True
    if done:
        out["summary"] = _summary(s)
    return out


def _summary(s: dict) -> dict:
    out = {
        "score": s["score"],
        "correct": s["correct"],
        "total": len(s["questions"]),
    }
    if s.get("xp"):
        out["xp"] = s["xp"]
    if s.get("streak"):
        out["streak"] = s["streak"]
    return out


def _challenge_done(conn, user_id: str, week: str) -> bool:
    """A finished challenge session this ISO week (whatever its country)."""
    return bool(
        conn.execute(
            "SELECT 1 FROM quiz_sessions WHERE user_id = ? AND mode = 'challenge'"
            " AND day LIKE ? AND finished_ms IS NOT NULL LIMIT 1",
            (user_id, f"{week}:%"),
        ).fetchone()
    )


def start(user_id: str, mode: str, pack: str | None) -> dict:
    ch = None
    if mode == "pack":
        if pack not in quiz_engine.PACKS:
            raise ApiError(422, "invalid_pack", "Unknown pack.")
    elif mode == "daily":
        pack = None
    elif mode == "challenge":
        ch = challenge_svc.current(
            user_id, datetime.fromtimestamp(_now_ms() / 1000, UTC).date()
        )
        pack = ch.get("pack")
    else:
        raise ApiError(422, "invalid_mode", "Unknown quiz mode.")
    now = _now_ms()
    day = ch["id"] if ch else _today(now)
    expired_id = None
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        s = quiz_db.latest_session(
            conn, user_id, mode, day, pack if ch is None else None
        )
        if mode == "challenge" and _challenge_done(conn, user_id, ch["week"]):
            raise ApiError(
                409, "already_done", "This week's challenge is already done."
            )
        if s and mode == "daily" and s["finished_ms"] is not None:
            raise ApiError(409, "already_done", "Today's daily quiz is already done.")
        rows = quiz_db.answers(conn, s["id"]) if s else []
        live = bool(s and s["finished_ms"] is None)
        if live and _expired(s, rows, now):
            expired_id = s["id"]
        elif live:
            return view(s, rows, resumed=True)
        else:
            sid = secrets.token_urlsafe(12)
            if ch:
                seed = f"challenge:{ch['id']}"
                questions = challenge_svc.questions_for(ch)
            else:
                seed = (
                    quiz_engine.daily_seed(date.fromisoformat(day))
                    if mode == "daily"
                    else secrets.token_hex(8)
                )
                questions = quiz_engine.build_questions(pack or "daily", seed)
            quiz_db.create_session(
                conn, sid, user_id, mode, pack, day, seed, questions, now
            )
            return view(quiz_db.get_session(conn, sid), quiz_db.answers(conn, sid))
    # idle with answers: close it as it stands. The daily and the challenge are
    # then done; a pack simply starts fresh.
    _finalize_expired(expired_id, now)
    if mode == "daily":
        raise ApiError(409, "already_done", "Today's daily quiz is already done.")
    if mode == "challenge":
        raise ApiError(409, "already_done", "This week's challenge is already done.")
    return start(user_id, mode, pack)


def get(user_id: str, sid: str) -> dict:
    now = _now_ms()
    with get_connection() as conn:
        s = quiz_db.get_session(conn, sid)
        if not s or s["user_id"] != user_id:
            raise ApiError(404, "session_not_found", "Quiz not found.")
        expired = _expired(s, quiz_db.answers(conn, sid), now)
    if expired:
        _finalize_expired(sid, now)
    with get_connection() as conn:
        s = quiz_db.get_session(conn, sid)
        return view(s, quiz_db.answers(conn, sid))


def _result(s: dict, row: dict, *, with_summary: bool) -> dict:
    out = {
        "correct": bool(row["correct"]),
        "correct_choice": s["questions"][row["idx"]]["answer"],
        "points": row["points"],
        "elapsed_ms": row["elapsed_ms"],
        "done": s["finished_ms"] is not None,
    }
    if out["done"] and with_summary:
        out["summary"] = _summary(s)
    return out


def answer(user_id: str, sid: str, index: int, choice: str) -> dict:
    now = _now_ms()
    expired = False
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        s = quiz_db.get_session(conn, sid)
        if not s or s["user_id"] != user_id:
            raise ApiError(404, "session_not_found", "Quiz not found.")
        qs = s["questions"]
        rows = quiz_db.answers(conn, sid)
        by_idx = {r["idx"]: r for r in rows}
        if not 0 <= index < len(qs):
            raise ApiError(422, "invalid_index", "No such question.")
        first = by_idx.get(index)
        if first is not None and first["answered_ms"] is not None:
            return _result(s, first, with_summary=True)  # first result stands
        if s["finished_ms"] is not None:
            raise ApiError(410, "session_expired", "This quiz timed out.")
        if _expired(s, rows, now):
            expired = True
        else:
            if choice not in [o["id"] for o in qs[index]["options"]]:
                raise ApiError(422, "invalid_choice", "Not one of the options.")
            if first is None:
                raise ApiError(422, "out_of_order", "Answer the questions in order.")
            elapsed = max(0, now - first["served_ms"])
            correct = choice == qs[index]["answer"]
            points = quiz_engine.points_for(correct, elapsed)
            quiz_db.record_answer(
                conn, sid, index, choice, correct, points, elapsed, now
            )
            row = {
                "idx": index,
                "correct": correct,
                "points": points,
                "elapsed_ms": elapsed,
            }
            if index + 1 < len(qs):
                quiz_db.serve_next(conn, sid, index + 1, now)
            else:
                done_rows = [
                    r
                    for r in rows
                    if r["answered_ms"] is not None and r["idx"] != index
                ]
                score = sum(r["points"] or 0 for r in done_rows) + points
                n_ok = sum(1 for r in done_rows if r["correct"]) + int(correct)
                quiz_db.finish(conn, sid, score, n_ok, now)
            s = quiz_db.get_session(conn, sid)
    if expired:
        _finalize_expired(sid, now)
        raise ApiError(410, "session_expired", "This quiz timed out.")
    if s["finished_ms"] is not None:
        s = _reward(s)
    return _result(s, row, with_summary=True)


def _merge(results: list[dict]) -> dict | None:
    results = [r for r in results if r]
    if not results:
        return None
    lv = [r["level_up"] for r in results if r.get("level_up")]
    return {
        "xp": results[-1]["xp"],
        "awards": [a for r in results for a in r["awards"]],
        "badges": [b for r in results for b in r["badges"]],
        "level_up": {"from": lv[0]["from"], "to": lv[-1]["to"]} if lv else None,
    }


def _reward(s: dict) -> dict:
    """XP and streak for a finished session, once (idempotent keys); stored
    on the session so a repeat answer reports the same summary."""
    uid, sid = s["user_id"], s["id"]
    xp = streak = None
    at = datetime.fromtimestamp(_now_ms() / 1000, UTC)
    if s["mode"] == "daily":
        # A daily finished after UTC midnight still belongs to its own day.
        at = datetime.fromisoformat(s["day"]).replace(hour=12, tzinfo=UTC)
    try:
        parts = []
        if s["mode"] == "h2h":
            from ...services import h2h

            xp = h2h.on_finished(s, at)
            return _store_rewards(sid, xp, None)
        if s["mode"] == "challenge":
            week = s["day"].split(":")[0]
            parts.append(
                game_engine.award(
                    uid,
                    "challenge_complete",
                    f"challenge_complete:{uid}:{week}",
                    now=at,
                )
            )
        elif s["mode"] == "daily":
            parts.append(
                game_engine.award(
                    uid, "quiz_daily", f"quiz_daily:{uid}:{s['day']}", now=at
                )
            )
            streak = game_engine.touch_streak(uid, "quiz", date.fromisoformat(s["day"]))
        else:
            parts.append(
                game_engine.award(uid, "quiz_pack", f"quiz_pack:{sid}", now=at)
            )
        if s["correct"] == len(s["questions"]):
            parts.append(
                game_engine.award(uid, "quiz_perfect", f"quiz_perfect:{sid}", now=at)
            )
        xp = _merge(parts)
    except Exception:
        logger.exception("quiz reward failed (session=%s)", sid)
        return s
    return _store_rewards(sid, xp, streak)


def _store_rewards(sid: str, xp: dict | None, streak: dict | None) -> dict:
    with get_connection() as conn:
        quiz_db.save_rewards(conn, sid, xp, streak)
        return quiz_db.get_session(conn, sid)


def history(user_id: str, limit: int) -> list[dict]:
    with get_connection() as conn:
        rows = quiz_db.history(conn, user_id, limit)
    return [
        {
            "session_id": r["id"],
            "mode": r["mode"],
            "pack": r["pack"],
            "score": r["score"],
            "correct": r["correct"],
            "finished_at": _iso(r["finished_ms"]),
        }
        for r in rows
    ]


def _streak_view(user_id: str, day: date) -> dict:
    per_week = game_engine.get_rules().streaks["quiz"].freeze_per_week
    with get_connection() as conn:
        row = game_db.get_streak(conn, user_id, "quiz")
    if not row:
        return {"current": 0, "longest": 0, "freeze_available": per_week > 0}
    fresh_week = row["freeze_week"] != game_engine._week(day)
    return {
        "current": row["current"],
        "longest": row["longest"],
        "freeze_available": (per_week if fresh_week else row["freezes"]) > 0,
    }


def state(user_id: str) -> dict:
    now = _now_ms()
    day = _today(now)
    with get_connection() as conn:
        s = quiz_db.latest_session(conn, user_id, "daily", day)
    if s:
        with get_connection() as conn:
            exp = _expired(s, quiz_db.answers(conn, s["id"]), now)
        if exp:
            _finalize_expired(s["id"], now)
            with get_connection() as conn:
                s = quiz_db.get_session(conn, s["id"])
    done = bool(s and s["finished_ms"] is not None)
    sizes = quiz_engine.pack_sizes()
    return {
        "daily": {
            "available": not done,
            "done": done,
            "score": s["score"] if done else None,
            "streak": _streak_view(user_id, date.fromisoformat(day)),
        },
        "packs": [
            {"id": p, "title_key": f"play.pack.{p}", "questions": sizes[p]}
            for p in quiz_engine.PACKS
        ],
        "challenge": _challenge_state(user_id, now),
        "open_h2h": _open_h2h(user_id, now),
    }


def challenge_public(user_id: str, ch: dict) -> dict:
    with get_connection() as conn:
        done = _challenge_done(conn, user_id, ch["week"])
    return challenge_svc.public(ch, done)


def _challenge_state(user_id: str, now: int) -> dict:
    ch = challenge_svc.current(user_id, datetime.fromtimestamp(now / 1000, UTC).date())
    return challenge_public(user_id, ch)


def _open_h2h(user_id: str, now: int) -> int:
    from ...services import h2h

    return h2h.waiting_for_you(user_id, now)
