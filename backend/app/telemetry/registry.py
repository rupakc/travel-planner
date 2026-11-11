"""Closed telemetry event registry and validation (pure: no I/O).

Every accepted event and prop is declared here. Anything else is dropped, so
free text, emails and other user content can never reach storage: ``id``
values are short tokens with no spaces or ``@``.
"""

import math
import re
import time
import uuid

PROP_TYPES = {"id", "int", "float", "bool"}  # plus "enum:a|b|c"

_ID_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,64}$")
MAX_SKEW_DAYS = 7  # how far a client `ts` may differ from server time
_MAX_SKEW_MS = MAX_SKEW_DAYS * 24 * 60 * 60 * 1000
_PLATFORMS = {"web", "android", "ios"}


def _enum(*values: str) -> str:
    return "enum:" + "|".join(values)


_AUTH_METHOD = _enum("password", "apple", "google", "facebook", "github")
_AUTH_MODE = _enum("signin", "signup", "link")

EVENTS: dict[str, dict[str, str]] = {
    "app_open": {},
    "app_background": {},
    "session_start": {},
    "screen_view": {"route": "id", "referrer_route": "id"},
    "screen_time": {"route": "id", "ms": "int"},
    "ui_tap": {"tid": "id", "route": "id"},
    "ui_toggle": {"tid": "id", "route": "id", "on": "bool"},
    "ui_change": {"tid": "id", "route": "id"},
    "ui_submit": {"tid": "id", "route": "id"},
    "search_submit": {
        "mode": _enum("search", "chat", "compare", "link", "discover"),
        "travelers": "int",
        "nights": "int",
        "multi_city": "bool",
    },
    "search_first_section": {"ms": "int"},
    "search_complete": {"ms": "int", "sections": "int", "errors": "int"},
    "search_abandon": {"ms": "int", "sections": "int"},
    "section_expand": {"section": "id"},
    "plan_select": {"section": "id"},
    "link_out": {"section": "id", "domain": "id"},
    "share": {"target": "id", "object": "id"},
    "alert_event": {"action": "id", "kind": "id"},
    "onboarding_step": {"step": "int", "action": _enum("view", "next", "skip", "done")},
    "theme_change": {"theme": _enum("system", "light", "dark")},
    "language_change": {"lang": _enum("en", "es", "de", "fr", "hi", "zh", "bn")},
    "consent": {"choice": _enum("granted", "denied")},
    "feature_used": {"feature": "id", "page": "id"},
    "perf": {
        "metric": _enum("ttfb", "fcp", "lcp", "inp", "cls", "long_task", "cold_start"),
        "value": "float",
        "route": "id",
    },
    "error": {"kind": _enum("js", "promise", "api"), "source": "id", "status": "int"},
    # Phase 1: accounts and game
    "auth_start": {"method": _AUTH_METHOD, "mode": _AUTH_MODE},
    "auth_result": {
        "method": _AUTH_METHOD,
        "mode": _AUTH_MODE,
        "result": _enum(
            "ok", "error", "cancelled", "coming_soon", "needs_username", "pending"
        ),
        "code": "id",
    },
    "signup_step": {"step": _enum("form", "check_email", "username", "done")},
    "email_verify": {
        "result": _enum("ok", "expired", "invalid", "used", "resent", "email_changed")
    },
    "password_reset": {
        "step": _enum("request", "confirm"),
        "result": _enum("ok", "error", "expired", "invalid", "used"),
    },
    "account_action": {
        "action": _enum(
            "avatar_upload",
            "avatar_remove",
            "name_change",
            "settings_change",
            "export",
            "delete",
            "link",
            "unlink",
            "signout_all",
            "email_verify_request",
            "change_password",
        )
    },
    "quota_block": {
        "bucket": _enum("search", "chat", "compare", "discover", "light_ai", "import"),
        "reason": _enum("daily_quota", "unverified"),
    },
    "game_award": {"rule": "id", "points": "int"},
    "badge_earned": {"badge": "id"},
    "level_up": {"level": "int"},
    "game_view": {"surface": _enum("account", "nav", "celebration")},
}


def _valid_id(v) -> bool:
    return isinstance(v, str) and _ID_RE.fullmatch(v) is not None


valid_id = _valid_id  # public: the route validates the event-level `screen` with it


_MAX_INT = 2**53


def _safe_number(v) -> bool:
    """A finite int/float within +-2**53 (checked before any float conversion,
    so a huge JSON integer is dropped instead of raising OverflowError)."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return -_MAX_INT <= v <= _MAX_INT
    return isinstance(v, float) and math.isfinite(v)


def _valid(value, typ: str) -> bool:
    if typ == "id":
        return _valid_id(value)
    if typ == "int":
        return isinstance(value, int) and _safe_number(value)
    if typ == "float":
        return _safe_number(value)
    if typ == "bool":
        return isinstance(value, bool)
    if typ.startswith("enum:"):
        return isinstance(value, str) and value in typ[5:].split("|")
    return False


def clean_event(raw: dict) -> dict | None:
    """Validate one event. Returns ``{"event", "ts", "props"}`` (ts in ms), or
    ``None`` for an unknown event. Bad or unknown props are dropped."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("event")
    schema = EVENTS.get(name) if isinstance(name, str) else None
    if schema is None:
        return None
    raw_props = raw.get("props")
    props: dict = {}
    if isinstance(raw_props, dict):
        for key, typ in schema.items():
            if key in raw_props and _valid(raw_props[key], typ):
                props[key] = raw_props[key]
    now = int(time.time() * 1000)
    ts = raw.get("ts")
    if not _safe_number(ts) or abs(ts - now) > _MAX_SKEW_MS:
        ts = now
    return {"event": name, "ts": int(ts), "props": props}


def _valid_uuid(v) -> bool:
    if not isinstance(v, str):
        return False
    try:
        uuid.UUID(v)
    except ValueError:
        return False
    return True


def clean_client(raw: dict) -> dict | None:
    """Validate the per-batch client block; ``None`` if any field is invalid."""
    if not isinstance(raw, dict):
        return None
    anon, session = raw.get("anon_id"), raw.get("session_id")
    platform, version, locale = (
        raw.get("platform"),
        raw.get("app_version"),
        raw.get("locale"),
    )
    if not (_valid_uuid(anon) and _valid_uuid(session)):
        return None
    if platform not in _PLATFORMS or not _valid_id(version):
        return None
    if not _valid_id(locale) or len(locale) > 16:
        return None
    return {
        "anon_id": anon,
        "session_id": session,
        "platform": platform,
        "app_version": version,
        "locale": locale,
    }
