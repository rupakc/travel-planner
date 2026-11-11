"""Game rules: validated config loaded from rules.json (or an override file)."""

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

BUILTIN_PATH = Path(__file__).with_name("rules.json")


class Rule(BaseModel):
    points: int = Field(ge=0)
    daily_cap: int = Field(ge=1)
    once: bool = False


class Badge(BaseModel):
    rule: str
    target: int = Field(ge=1)
    tier: Literal["bronze", "silver", "gold"]
    icon: str


class Levels(BaseModel):
    min_xp: list[int] = Field(min_length=1)


class Streak(BaseModel):
    freeze_per_week: int = Field(ge=0)


class Rules(BaseModel):
    version: int = 1
    rules: dict[str, Rule]
    badges: dict[str, Badge]
    levels: Levels
    streaks: dict[str, Streak]


def _read(path: Path) -> Rules:
    rules = Rules.model_validate(json.loads(path.read_text(encoding="utf-8")))
    for bid, b in rules.badges.items():
        if b.rule not in rules.rules:
            raise ValueError(f"badge {bid} references unknown rule {b.rule}")
    mins = rules.levels.min_xp
    if mins[0] != 0 or mins != sorted(mins):
        raise ValueError("levels.min_xp must start at 0 and ascend")
    return rules


def load_rules(path: str | None = None) -> Rules:
    if path:
        try:
            return _read(Path(path))
        except (OSError, ValueError, ValidationError) as e:
            logger.error("invalid game rules override %s: %s; using built-in", path, e)
    return _read(BUILTIN_PATH)
