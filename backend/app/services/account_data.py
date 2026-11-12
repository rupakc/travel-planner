"""Export my data and in-app account deletion (contract: GET /account/export,
DELETE /account).

Every main-DB table that holds a user's rows is listed below;
``tests/test_account_data.py`` introspects the schema and fails when a new
table with a ``username`` / ``user_id`` / ``created_by`` / ``user_key`` /
``watch_id`` column is not covered here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime
from typing import Literal

from ..core.session_payload import user_payload
from ..db import fare_watch_db, game_db, price_watch_db, telemetry_db, users_db
from ..db import user_settings_db as sdb
from ..db.database import get_connection
from ..db.devices_db import masked
from ..db.trip_children import TRIP_CHILD_TABLES
from ..db.trip_snapshot_db import get_snapshot
from ..db.user_countries_db import list_countries
from ..game import engine
from .avatar import remove_avatar
from .oauth import registry, secrets_box

logger = logging.getLogger(__name__)

# table → (column, which user attribute it holds)
USER_TABLES: dict[str, tuple[str, Literal["id", "username"]]] = {
    "plans": ("username", "username"),
    "preferences": ("username", "username"),
    "recent_searches": ("username", "username"),
    "taste_signals": ("username", "username"),
    "feedback": ("username", "username"),
    "devices": ("username", "username"),
    "notifications": ("user_id", "id"),
    "fare_watches": ("user_id", "id"),
    "fare_watch_user_quota": ("user_id", "id"),
    "price_watches": ("user_id", "id"),
    "alert_prefs": ("user_id", "id"),
    "alert_savings": ("user_id", "id"),
    "alert_outbox": ("user_id", "id"),
    "alert_digests": ("user_id", "id"),
    "notify_prefs": ("user_id", "id"),
    "notify_log": ("user_id", "id"),
    "account_tokens": ("user_id", "id"),
    "refresh_tokens": ("user_id", "id"),
    "user_identities": ("user_id", "id"),
    "oauth_tickets": ("user_id", "id"),
    "user_settings": ("user_id", "id"),
    "user_onboarding": ("user_id", "id"),
    "xp_ledger": ("user_id", "id"),
    "user_badges": ("user_id", "id"),
    "user_streaks": ("user_id", "id"),
    "user_countries": ("user_id", "id"),
    "shares": ("username", "username"),
    "social_profiles": ("user_id", "id"),
    "social_limits": ("user_id", "id"),
}

# child table → WHERE clause over its parent; the one parameter is the user id
_USER_PLANS = (
    "plan_id IN (SELECT id FROM plans WHERE username ="
    " (SELECT username FROM users WHERE id = ?))"
)
CHILD_TABLES: dict[str, str] = {
    "fare_watch_history": "watch_id IN (SELECT id FROM fare_watches WHERE user_id = ?)",
    "price_watch_history": "watch_id IN (SELECT id FROM price_watches WHERE user_id = ?)",
    # cached advice is keyed by (kind, watch): a flight is a fare watch
    "alert_advice": (
        "EXISTS (SELECT 1 FROM users u WHERE u.id = ? AND ("
        "(watch_kind = 'flight' AND watch_id IN"
        " (SELECT id FROM fare_watches WHERE user_id = u.id))"
        " OR (watch_kind != 'flight' AND watch_id IN"
        " (SELECT id FROM price_watches WHERE user_id = u.id))))"
    ),
    **dict.fromkeys(TRIP_CHILD_TABLES, _USER_PLANS),
}

# tables keyed by a value derived from the user id; the parameter is the user id
KEYED_TABLES: dict[str, str] = {
    "ai_usage_daily": "user_key = 'user:' || ?",
    # a follow or block row holds the user on either side
    "social_follows": "? IN (follower_id, followee_id)",
    "social_blocks": "? IN (blocker_id, blocked_id)",
}

# rows that outlive the user, with the reference cleared: table → column
KEEP_NULLED: dict[str, str] = {
    "invite_codes": "created_by",
}

# never in an export, at any depth
_SECRET_KEYS = frozenset(
    {"password_hash", "token_hash", "secret_enc", "refresh_token", "code_hash"}
)


class LastAdminError(Exception):
    """Deleting this account would leave no active admin."""


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k not in _SECRET_KEYS}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def _rows(sql: str, params: tuple) -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# export key → (child table, ORDER BY)
_TRIP_EXPORT = {
    "expenses": ("trip_expenses", "spent_on, created_at, id"),
    "journal": ("trip_journal", "created_at, id"),
    "places": ("trip_ratings", "updated_at, place_key"),
    "prep": ("trip_prep", "item_id"),
    "checkins": ("trip_checkins", "day"),
}


def _parse_meta(row: dict) -> dict:
    if isinstance(row.get("meta"), str):
        try:
            row["meta"] = json.loads(row["meta"])
        except ValueError:
            pass
    return row


def _trip_export(plan_id: int) -> dict:
    out: dict = {}
    for key, (table, order) in _TRIP_EXPORT.items():
        rows = _rows(
            f"SELECT * FROM {table} WHERE plan_id = ? ORDER BY {order}",  # nosec B608
            (plan_id,),
        )
        out[key] = [
            _parse_meta({k: v for k, v in r.items() if k != "plan_id"}) for r in rows
        ]
    out["snapshot"] = get_snapshot(plan_id)
    return out


def export_user(user: dict) -> dict:
    """Everything stored about ``user``, in the contract's shape."""
    from ..db import (
        notifications_db,
        plans_db,
        preferences_db,
        recent_searches_db,
        taste_db,
    )
    from ..db.feedback_db import _row_to_dict as feedback_row
    from . import notify_settings

    uid, name = user["id"], user["username"]
    account = {
        **user_payload(user),
        "created_at": user.get("created_at"),
        "locale": user.get("locale"),
        "last_login_at": user.get("last_login_at"),
    }
    identities = _rows(
        """SELECT provider, subject, email, email_verified, display_name,
                  picture_url, created_at AS linked_at, last_used_at
           FROM user_identities WHERE user_id = ? ORDER BY created_at, id""",
        (uid,),
    )
    for i in identities:
        i["email_verified"] = bool(i["email_verified"])
    fare_watches = [
        {**w, "history": fare_watch_db.get_history(w["id"])}
        for w in fare_watch_db.list_watches(uid)
    ]
    price_watches = [
        {**w, "history": price_watch_db.get_history(w["id"])}
        for w in price_watch_db.list_watches(uid)
    ]
    notifications = notifications_db.list_notifications(uid, limit=1_000_000)
    notify_log = _rows(
        """SELECT id, plan_id, kind, category, status, due_at, sent_at,
                  dropped_reason, notification_id, created_at
           FROM notify_log WHERE user_id = ? ORDER BY id""",
        (uid,),
    )
    devices = [
        {k: v for k, v in d.items() if k != "username"} | {"token": masked(d["token"])}
        for d in _rows("SELECT * FROM devices WHERE username = ? ORDER BY id", (name,))
    ]
    feedback = [
        {k: v for k, v in feedback_row(r).items() if k != "username"}
        for r in _rows(
            "SELECT * FROM feedback WHERE username = ? ORDER BY created_at", (name,)
        )
    ]
    taste = {
        **taste_db.get_taste_profile(name),
        "raw": _rows(
            """SELECT signal_type, value, weight, created_at FROM taste_signals
               WHERE username = ? ORDER BY id""",
            (name,),
        ),
    }
    game = {
        **engine.summary(uid, hidden=game_db.hide_game(uid)),
        "ledger": _rows(
            """SELECT rule, points, created_at FROM xp_ledger
               WHERE user_id = ? ORDER BY created_at, id""",
            (uid,),
        ),
    }
    plans = plans_db.get_user_plans(name)
    return _scrub(
        {
            "format": "voyager-export",
            "version": 1,
            "exported_at": _iso_z(datetime.now(UTC)),
            "account": account,
            "identities": identities,
            "settings": sdb.get_settings(uid),
            "onboarding": sdb.get_onboarding(uid),
            "preferences": preferences_db.get_preferences(name),
            "plans": plans,
            "trips": {str(p["id"]): _trip_export(p["id"]) for p in plans},
            "countries": [
                {k: v for k, v in c.items() if k != "user_id"}
                for c in list_countries(uid)
            ],
            "recent_searches": recent_searches_db.list_recent_searches(name),
            "taste": taste,
            "feedback": feedback,
            "fare_watches": fare_watches,
            "price_watches": price_watches,
            "notifications": notifications["items"],
            "devices": devices,
            "notification_settings": notify_settings.stored(uid),
            "notify_log": notify_log,
            "game": game,
        }
    )


def _active_admins(conn: sqlite3.Connection) -> int:
    return conn.execute(
        """SELECT COUNT(*) FROM users WHERE is_admin = 1 AND is_active = 1
           AND account_status = 'active'"""
    ).fetchone()[0]


def delete_rows(user: dict) -> list[tuple[str, str]]:
    """Delete every main-DB row of ``user`` in one transaction. Returns the
    (provider, sealed secret) pairs of the identities it removed, for revoking.
    Raises LastAdminError (nothing deleted) when ``user`` is the only active
    admin."""
    uid, name = user["id"], user["username"]
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT is_admin, is_active, account_status FROM users WHERE id = ?",
            (uid,),
        ).fetchone()
        if (
            row
            and row["is_admin"]
            and row["is_active"]
            and row["account_status"] == "active"
            and _active_admins(conn) <= 1
        ):
            raise LastAdminError
        secrets = [
            (r["provider"], r["secret_enc"])
            for r in conn.execute(
                """SELECT provider, secret_enc FROM user_identities
                   WHERE user_id = ? AND secret_enc IS NOT NULL""",
                (uid,),
            )
        ]
        for table, where in {**CHILD_TABLES, **KEYED_TABLES}.items():
            conn.execute(f"DELETE FROM {table} WHERE {where}", (uid,))  # nosec B608
        for table, (col, key) in USER_TABLES.items():
            conn.execute(
                f"DELETE FROM {table} WHERE {col} = ?",  # nosec B608
                (uid if key == "id" else name,),
            )
        for table, col in KEEP_NULLED.items():
            conn.execute(
                f"UPDATE {table} SET {col} = NULL WHERE {col} IN (?, ?)",  # nosec B608
                (uid, name),
            )
        users_db._delete_user_rows(conn, uid)
    return secrets


# revocations still running after their request went away (strong refs)
_pending: set[asyncio.Task] = set()


def _step(name: str, fn, *args) -> None:
    try:
        fn(*args)
    except Exception as exc:  # best effort: the rows are already gone
        logger.warning("account_delete: %s failed (%s)", name, type(exc).__name__)


async def _revoke(provider_id: str, sealed: str) -> None:
    try:
        provider = registry.get_provider(provider_id)
        if provider is None:
            logger.warning("account_delete: no %s adapter to revoke with", provider_id)
            return
        secret = secrets_box.open_(sealed)
        if not secret:
            logger.warning(
                "account_delete: %s secret unreadable, not revoked", provider_id
            )
            return
        await provider.revoke(secret)
    except Exception as exc:  # best effort; never log the secret
        logger.warning(
            "account_delete: %s revoke failed (%s)", provider_id, type(exc).__name__
        )


async def _revoke_all(secrets: list[tuple[str, str]]) -> None:
    for provider_id, sealed in secrets:
        await _revoke(provider_id, sealed)


def _delete_local(user: dict) -> list[tuple[str, str]]:
    """The blocking part of a deletion (DB transaction, telemetry rows, avatar
    file); runs in a worker thread. Returns the provider secrets to revoke."""
    uid = user["id"]
    secrets = delete_rows(user)
    _step("telemetry delete", telemetry_db.delete_user_events, uid)
    _step("avatar removal", remove_avatar, uid)
    logger.info("account_delete: account deleted")
    return secrets


async def _delete_and_revoke(user: dict) -> None:
    secrets = await asyncio.to_thread(_delete_local, user)
    if secrets:
        await _revoke_all(secrets)


async def delete_user(user: dict) -> None:
    """Delete the account and everything the export lists, the user's raw
    telemetry and avatar file, and revoke stored provider tokens (Apple).

    The DB rows go first, in one transaction, so a failure leaves the account
    whole. The blocking local work (rows, telemetry, avatar file) runs in a
    worker thread, off the event loop, each post-commit step caught and
    logged; then the network revocations. The whole sequence is one task
    shielded from the request's cancellation (a client disconnect lets it
    finish)."""
    task = asyncio.create_task(_delete_and_revoke(user))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    await asyncio.shield(task)
