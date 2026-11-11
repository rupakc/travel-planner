"""Account resolution for a provider sign-in: which user a provider identity
belongs to, when it may be linked, and creating the account on ``complete``.

Auto-link happens only to an active account whose email we verified, and only
from a provider email that is verified *and* trusted. A pending (unverified)
native account with the same email is deleted, never linked.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import re
import secrets
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ...core.config import settings
from ...db import oauth_db, users_db
from ...db.database import get_connection
from ...db.reserved_usernames import RESERVED_USERNAMES
from .base import ProviderProfile
from .secrets_box import seal

logger = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")


@dataclass(frozen=True)
class SignedIn:
    user: dict


@dataclass(frozen=True)
class Linked:
    user: dict


@dataclass(frozen=True)
class NeedsUsername:
    pending_data: dict


@dataclass(frozen=True)
class Refused:
    code: str


Result = SignedIn | Linked | NeedsUsername | Refused


def _now() -> datetime:
    return datetime.now(UTC)


def _active(user: dict) -> bool:
    return bool(user.get("is_active")) and user.get("account_status") == "active"


def _sealed(secret: str | None) -> str | None:
    return seal(secret) if secret else None


def _email(profile: ProviderProfile) -> str | None:
    e = (profile.email or "").strip().lower()
    return e or None


def _attach(user_id: str, provider: str, profile: ProviderProfile, secret_enc):
    oauth_db.add_identity(
        user_id,
        provider,
        profile.subject,
        email=_email(profile),
        email_verified=profile.email_verified,
        display_name=profile.display_name,
        picture_url=profile.picture_url,
        secret_enc=secret_enc,
    )


def _delete_pending_with_email(email: str) -> int:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM users WHERE lower(email) = ? AND account_status = 'pending'",
            (email,),
        ).fetchall()
        for r in rows:
            users_db._delete_user_rows(conn, r["id"])
    if rows:
        logger.info("oauth.pending_replaced count=%d", len(rows))
    return len(rows)


def resolve_identity(
    profile: ProviderProfile,
    provider: str,
    *,
    link_user_id: str | None,
    secret: str | None,
) -> Result:
    secret_enc = _sealed(secret)
    email = _email(profile)

    # 1. a known identity
    known = oauth_db.get_identity(provider, profile.subject)
    if known:
        if link_user_id and known["user_id"] != link_user_id:
            return Refused("identity_in_use")
        user = users_db.get_user_by_id(known["user_id"])
        if not user or not _active(user):
            return Refused("account_inactive")
        oauth_db.touch_identity(
            known["id"],
            email=email,
            email_verified=profile.email_verified,
            secret_enc=secret_enc,
        )
        return Linked(user) if link_user_id else SignedIn(user)

    # 2. linking from a signed-in session
    if link_user_id:
        user = users_db.get_user_by_id(link_user_id)
        if not user or not _active(user):
            return Refused("account_inactive")
        try:
            _attach(user["id"], provider, profile, secret_enc)
        except sqlite3.IntegrityError:
            return Refused("identity_in_use")
        return Linked(user)

    if email:
        holder = users_db.get_user_by_email(email)
        # 3. auto-link: verified + trusted provider email, verified account email
        if (
            holder
            and profile.email_verified
            and profile.email_trusted
            and holder.get("account_status") == "active"
            and holder.get("email_verified")
        ):
            if not holder.get("is_active"):
                return Refused("account_inactive")
            try:
                _attach(holder["id"], provider, profile, secret_enc)
            except sqlite3.IntegrityError:
                return Refused("identity_in_use")
            return SignedIn(holder)
        # 4. a pending native account is replaced, never linked
        if holder and holder.get("account_status") == "pending":
            _delete_pending_with_email(email)
            holder = users_db.get_user_by_email(email)
        # 5. the email belongs to an account we can't link to
        if holder:
            if not holder.get("is_active"):
                return Refused("account_inactive")
            return Refused("email_in_use_unverified")

    # 6. a new account
    return NeedsUsername(
        {
            "provider": provider,
            "subject": profile.subject,
            "email": email,
            "email_verified": bool(profile.email_verified),
            "email_trusted": bool(profile.email_trusted),
            "display_name": profile.display_name,
            "picture_url": profile.picture_url,
            "secret_enc": secret_enc,
        }
    )


# ── Usernames ────────────────────────────────────────────────────────────────


def _fold(text: str) -> str:
    ascii_ = (
        unicodedata.normalize("NFKD", text or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9_]", "_", ascii_)).strip("_")


def _usable(name: str, now: datetime) -> bool:
    return (
        bool(USERNAME_RE.match(name))
        and name not in RESERVED_USERNAMES
        and users_db.username_available(name, now)
    )


def suggest_username(email: str | None, name: str | None) -> str:
    """The email local part (else the name) folded to ``[a-z0-9_]``, 3–20
    characters, with ``_2``, ``_3``, … until available."""
    local = (email or "").split("@", 1)[0]
    base = _fold(local) or _fold(name or "") or "traveller"
    base = base[:20].rstrip("_") or "traveller"
    while len(base) < 3:
        base += "0"
    now = _now()
    if _usable(base, now):
        return base
    for n in range(2, 10_000):
        suffix = f"_{n}"
        candidate = base[: 20 - len(suffix)].rstrip("_") + suffix
        if _usable(candidate, now):
            return candidate
    return f"t_{secrets.token_hex(4)}"


# ── Account creation ─────────────────────────────────────────────────────────


class UsernameTaken(Exception):
    pass


class EmailTaken(Exception):
    pass


def create_oauth_user(
    pending: dict,
    *,
    username: str,
    display_name: str | None,
    locale: str | None,
    invite_id: int | None,
) -> dict:
    """Insert the user and its identity. Raises UsernameTaken / EmailTaken."""
    email = pending.get("email")
    trusted = bool(pending.get("email_verified") and pending.get("email_trusted"))
    if email:
        _delete_pending_with_email(email)
        if users_db.get_user_by_email(email):
            raise EmailTaken
    if not users_db.username_available(username, _now()):
        raise UsernameTaken
    try:
        user = users_db.create_user(
            username,
            password_hash="!",
            email=email,
            is_first_login=False,
            signup_method="oauth",
            email_verified=False,
            display_name=display_name,
            locale=locale,
        )
    except users_db.UsernameTakenError as exc:
        raise UsernameTaken from exc
    except sqlite3.IntegrityError as exc:
        if "email" in str(exc):
            raise EmailTaken from exc
        raise UsernameTaken from exc
    if invite_id is not None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET invite_id = ? WHERE id = ?", (invite_id, user["id"])
            )
    try:
        oauth_db.add_identity(
            user["id"],
            pending["provider"],
            pending["subject"],
            email=email,
            email_verified=bool(pending.get("email_verified")),
            display_name=pending.get("display_name"),
            picture_url=pending.get("picture_url"),
            secret_enc=pending.get("secret_enc"),
        )
    except sqlite3.IntegrityError:
        # the same provider account finished another sign-up first
        users_db.delete_user_row(user["id"])
        raise
    if email and trusted:
        users_db.mark_email_verified(user["id"], email)
    return users_db.get_user_by_id(user["id"])


def issue_verify_token(user_id: str, email: str) -> str:
    """A verify-email token (Task 27's issue_token when present)."""
    try:
        tokens_db = importlib.import_module("app.db.account_tokens_db")
    except ImportError:
        tokens_db = None
    if tokens_db is not None and hasattr(tokens_db, "issue_token"):
        return tokens_db.issue_token(user_id, "verify_email", email)
    token = secrets.token_urlsafe(32)
    now = _now()
    ttl = timedelta(minutes=int(settings.account_token_ttl_minutes))
    with get_connection() as conn:
        conn.execute(
            """UPDATE account_tokens SET used_at = ? WHERE user_id = ?
               AND purpose = 'verify_email' AND used_at IS NULL""",
            (now.isoformat(), user_id),
        )
        conn.execute(
            """INSERT INTO account_tokens
               (user_id, purpose, token_hash, email, created_at, expires_at)
               VALUES (?, 'verify_email', ?, ?, ?, ?)""",
            (
                user_id,
                hashlib.sha256(token.encode()).hexdigest(),
                email,
                now.isoformat(),
                (now + ttl).isoformat(),
            ),
        )
    return token
