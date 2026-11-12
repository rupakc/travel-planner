"""Social profile rules: handles and the privacy projection.

A handle is the only public identity. ``project`` is a pure function that
turns a stored profile into what one viewer may see; every optional field is
absent unless its owner opted in, and the loaders for them are only called
when needed.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ..db import places_db
from ..db.reserved_usernames import RESERVED_USERNAMES
from . import moderation

HANDLE_RE = re.compile(r"^[a-z0-9_]{3,20}$")
HANDLE_CHANGE_DAYS = 30
VISIBILITIES = ("private", "followers", "public")
BIO_MAX = 160

# words that read as official or collide with SPA routes (/u/<handle>, /feed ...)
RESERVED_HANDLES: frozenset[str] = RESERVED_USERNAMES | frozenset(
    {
        "feed", "play", "social", "profile", "profiles", "follow", "following",
        "followers", "blocks", "block", "ideas", "idea", "new", "u", "you",
        "voyagerteam", "team", "security", "abuse", "privacy", "legal",
        "moderation", "mod", "mods", "everyone", "anonymous", "deleted",
        "leaderboard", "quiz", "h2h", "challenge", "game", "trips", "trip",
        "search", "chat", "share", "shares", "notifications", "preferences",
    }
)  # fmt: skip


def handle_problem(handle: str) -> str | None:
    """``invalid`` / ``reserved`` for a handle that can never be taken, else None."""
    h = (handle or "").strip().lower()
    if not HANDLE_RE.match(h):
        return "invalid"
    if h in RESERVED_HANDLES or moderation.check(h.replace("_", " ")) != "allow":
        return "reserved"
    return None


def parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def handle_change_wait(profile: dict | None, now: datetime | None = None) -> int:
    """Seconds until the handle may change again (0 = now). The first handle
    is free; the 30-day clock starts at the first change."""
    changed = parse_ts((profile or {}).get("handle_changed_at"))
    if not changed:
        return 0
    left = changed + timedelta(days=HANDLE_CHANGE_DAYS) - (now or datetime.now(UTC))
    return max(0, int(left.total_seconds()))


def valid_country(code: str) -> bool:
    return (code or "").upper() in places_db._iso_codes()


def own_view(profile: dict | None) -> dict:
    """``GET /social/profile``: the caller's settings (defaults when none)."""
    p = profile or {}
    return {
        "handle": p.get("handle"),
        "visibility": p.get("visibility", "private"),
        "bio": p.get("bio", ""),
        "show_avatar": p.get("show_avatar", False),
        "show_home_country": p.get("show_home_country", False),
        "show_countries": p.get("show_countries", False),
        "show_level": p.get("show_level", False),
        "show_badges": p.get("show_badges", False),
        "leaderboard_opt_in": p.get("leaderboard_opt_in", False),
        "home_country": p.get("home_country"),
        "created_at": p.get("created_at"),
    }


def can_view(profile: dict | None, *, blocked: bool, own: bool) -> bool:
    """Whether the profile exists for this viewer at all (else 404)."""
    if not profile:
        return False
    if own:
        return True
    if blocked or profile["visibility"] == "private":
        return False
    return True


def project(
    profile: dict,
    *,
    own: bool,
    following: bool,
    hidden_game: bool,
    counts: dict,
    you: dict,
    avatar: Callable[[], str | None],
    countries: Callable[[], list[str]],
    game: Callable[[], dict],
) -> dict:
    """What one viewer sees. A ``followers`` profile shows non-followers only
    the handle and counts; otherwise each extra appears only if opted in."""
    out: dict = {"handle": profile["handle"]}
    full = own or following or profile["visibility"] == "public"
    if full:
        out["bio"] = profile["bio"]
        if profile["show_avatar"] and (url := avatar()):
            out["avatar_url"] = url
        if profile["show_home_country"] and profile.get("home_country"):
            out["home_country"] = profile["home_country"]
        if profile["show_countries"]:
            out["countries"] = countries()
        if not hidden_game and (profile["show_level"] or profile["show_badges"]):
            g = game()
            if profile["show_level"]:
                out["level"] = g["level"]
            if profile["show_badges"]:
                out["badges"] = g["badges"]
    out.update(counts)
    out["you"] = you
    return out
