"""Per-user settings and onboarding state (tables from accounts_schema)."""

import json
import re
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .database import get_connection

DEFAULT_SETTINGS: dict = {
    "language": None,
    "theme": "system",
    "currency": "USD",
    "units": "metric",
    "timezone": None,
    "hide_game": False,
    "hide_community": False,
    "profile_visibility": "public",
    "telemetry_opt_out": False,
    "bucket_list_goal": None,
}

DEFAULT_ONBOARDING: dict = {
    "step": 0,
    "done": False,
    "skipped": False,
    "traveller_type": None,
    "completed_at": None,
}


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Literal["en", "es", "de", "fr", "hi", "zh", "bn"] | None = None
    theme: Literal["system", "light", "dark"] = "system"
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    units: Literal["metric", "imperial"] = "metric"
    timezone: str | None = None
    hide_game: bool = False
    hide_community: bool = False
    profile_visibility: Literal["public", "followers", "private"] = "public"
    telemetry_opt_out: bool = False
    bucket_list_goal: int | None = Field(default=None, ge=1, le=250)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise ValueError("unknown timezone") from None
        return v


def _now() -> str:
    return datetime.now(UTC).isoformat()


def get_settings(user_id: str) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT data FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
    stored: dict = {}
    if row:
        try:
            loaded = json.loads(row["data"])
            if isinstance(loaded, dict):
                stored = loaded
        except ValueError:
            pass
    return {
        **DEFAULT_SETTINGS,
        **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS},
    }


def patch_settings(user_id: str, changes: dict) -> dict:
    """``changes`` holds only the keys the caller sent; each is validated."""
    unknown = set(changes) - set(DEFAULT_SETTINGS)
    if unknown:
        raise ValueError(f"unknown settings: {sorted(unknown)}")
    validated = SettingsPatch(**changes).model_dump(include=set(changes))
    merged = {**get_settings(user_id), **validated}
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_settings (user_id, data, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET data = excluded.data,
                   updated_at = excluded.updated_at""",
            (user_id, json.dumps(merged), _now()),
        )
    return merged


def get_onboarding(user_id: str) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM user_onboarding WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row:
        return dict(DEFAULT_ONBOARDING)
    return {
        "step": row["step"],
        "done": bool(row["done"]),
        "skipped": bool(row["skipped"]),
        "traveller_type": row["traveller_type"],
        "completed_at": row["completed_at"],
    }


_TYPE_RE = re.compile(r"^[a-z_]{1,32}$")


def put_onboarding(
    user_id: str,
    step: int,
    done: bool,
    skipped: bool = False,
    traveller_type: str | None = None,
) -> tuple[dict, bool]:
    """Returns (onboarding, newly_awardable). ``done`` never goes back to
    false; the award is for the first completion that is not a skip."""
    if traveller_type is not None and not _TYPE_RE.match(traveller_type):
        raise ValueError("traveller_type")
    cur = get_onboarding(user_id)
    now = _now()
    new_done = cur["done"] or done
    newly = done and not cur["done"]
    new_skipped = cur["skipped"] if cur["done"] else skipped
    ttype = traveller_type if traveller_type is not None else cur["traveller_type"]
    completed = cur["completed_at"] or (now if newly else None)
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_onboarding
                   (user_id, step, done, skipped, traveller_type, completed_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET step = excluded.step,
                   done = excluded.done, skipped = excluded.skipped,
                   traveller_type = excluded.traveller_type,
                   completed_at = excluded.completed_at,
                   updated_at = excluded.updated_at""",
            (user_id, step, int(new_done), int(new_skipped), ttype, completed, now),
        )
    out = {
        "step": step,
        "done": new_done,
        "skipped": new_skipped,
        "traveller_type": ttype,
        "completed_at": completed,
    }
    return out, bool(newly and not new_skipped)
