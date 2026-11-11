"""Account resolution for a provider sign-in: which user a provider identity
belongs to, when it may be linked, and creating the account on ``complete``.

Auto-link happens only to an active account whose email we verified, and only
from a provider email that is verified *and* trusted. A pending (unverified)
native account with the same email is deleted, never linked.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import secrets
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from ...db import account_tokens_db, invites_db, oauth_db, users_db
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


def _delete_pending_in(conn: sqlite3.Connection, email: str) -> int:
    rows = conn.execute(
        "SELECT id FROM users WHERE lower(email) = ? AND account_status = 'pending'",
        (email,),
    ).fetchall()
    for r in rows:
        users_db._delete_user_rows(conn, r["id"])
    if rows:
        logger.info("oauth.pending_replaced count=%d", len(rows))
    return len(rows)


def _delete_pending_with_email(email: str) -> int:
    with get_connection() as conn:
        return _delete_pending_in(conn, email)


def _trusted(profile_or_pending) -> bool:
    if isinstance(profile_or_pending, dict):
        return bool(
            profile_or_pending.get("email_verified")
            and profile_or_pending.get("email_trusted")
        )
    return bool(profile_or_pending.email_verified and profile_or_pending.email_trusted)


def profile_to_dict(profile: ProviderProfile) -> dict:
    return dataclasses.asdict(profile)


def profile_from_dict(data: dict) -> ProviderProfile:
    fields = {f.name for f in dataclasses.fields(ProviderProfile)}
    return ProviderProfile(**{k: v for k, v in data.items() if k in fields})


def precheck_link(
    profile: ProviderProfile, provider: str, link_user_id: str
) -> Refused | None:
    """The refusals a link would hit, without attaching anything (the attach
    happens only after the exchange proved the browser or app)."""
    known = oauth_db.get_identity(provider, profile.subject)
    if known and known["user_id"] != link_user_id:
        return Refused("identity_in_use")
    user = users_db.get_user_by_id(link_user_id)
    if not user or not _active(user):
        return Refused("account_inactive")
    return None


def resolve_identity(
    profile: ProviderProfile,
    provider: str,
    *,
    link_user_id: str | None,
    secret: str | None,
    secret_enc: str | None = None,
) -> Result:
    """``secret_enc`` (already sealed) is used when ``secret`` is None."""
    secret_enc = _sealed(secret) or secret_enc
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
        # 4. a pending native account is replaced (never linked), but only on
        # a verified + trusted email: an untrusted claim can't evict anyone
        if holder and holder.get("account_status") == "pending" and _trusted(profile):
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


class InviteInvalid(Exception):
    pass


class IdentityTaken(Exception):
    pass


def create_oauth_user(
    pending: dict,
    *,
    username: str,
    display_name: str | None,
    locale: str | None,
    invite_code: str | None,
) -> dict:
    """Insert the user, its identity and (with ``invite_code``) the invite use
    in one ``BEGIN IMMEDIATE`` transaction: any failure rolls all of it back.
    Raises UsernameTaken / EmailTaken / InviteInvalid / IdentityTaken."""
    email = pending.get("email")
    trusted = _trusted(pending)
    uid = str(uuid.uuid4())
    now = _now()
    ts = now.isoformat()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        invite_id = None
        if invite_code is not None:
            h = invites_db._hash(invite_code)
            cur = conn.execute(
                "UPDATE invite_codes SET uses = uses + 1 WHERE code_hash = ?"
                " AND uses < max_uses AND revoked_at IS NULL AND expires_at > ?",
                (h, ts),
            )
            if cur.rowcount != 1:
                raise InviteInvalid
            invite_id = conn.execute(
                "SELECT id FROM invite_codes WHERE code_hash = ?", (h,)
            ).fetchone()["id"]
        if email:
            if trusted:
                _delete_pending_in(conn, email)
            if conn.execute(
                "SELECT 1 FROM users WHERE lower(email) = ?", (email,)
            ).fetchone():
                raise EmailTaken
        if users_db._holder_blocks(conn, username, now):
            raise UsernameTaken
        if conn.execute(
            "SELECT 1 FROM user_identities WHERE provider = ? AND subject = ?",
            (pending["provider"], pending["subject"]),
        ).fetchone():
            raise IdentityTaken
        verified = bool(email and trusted)
        conn.execute(
            """INSERT INTO users
               (id, username, email, password_hash, is_admin, is_first_login, is_active,
                created_at, updated_at, signup_method, account_status, email_verified,
                verified_at, display_name, locale, invite_id)
               VALUES (?, ?, ?, '!', 0, 0, 1, ?, ?, 'oauth', 'active', ?, ?, ?, ?, ?)""",
            (uid, username, email, ts, ts, int(verified), ts if verified else None,
             display_name, locale, invite_id),
        )  # fmt: skip
        conn.execute(
            """INSERT INTO user_identities
               (user_id, provider, subject, email, email_verified, display_name,
                picture_url, secret_enc, created_at, last_used_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uid, pending["provider"], pending["subject"], email,
             int(bool(pending.get("email_verified"))), pending.get("display_name"),
             pending.get("picture_url"), pending.get("secret_enc"),
             oauth_db.iso(now), oauth_db.iso(now)),
        )  # fmt: skip
    return users_db.get_user_by_id(uid)


def issue_verify_token(user_id: str, email: str) -> str:
    """A verify-email token (Task 27's account tokens)."""
    return account_tokens_db.issue_token(user_id, "verify_email", email)
