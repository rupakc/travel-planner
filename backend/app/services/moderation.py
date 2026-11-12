"""Deterministic text moderation for user-written social text (no model call).

``check`` answers ``allow``, ``review`` (hold for an admin) or ``reject``:
a term on the committed reject list rejects; a term on the review list, or
any URL or email-like token, is held. ``plain_text`` makes stored text plain
(control characters removed, whitespace collapsed, length capped). Phase 5
T2 extends this module; ``classify`` is the optional-classifier hook.
"""

import json
import re
import unicodedata
from functools import cache
from pathlib import Path
from typing import Literal

Verdict = Literal["allow", "review", "reject"]

_URL = re.compile(
    r"(https?://|www\.|ftp://|\b[a-z0-9-]+\.(com|net|org|io|co|me|ly|xyz|info|ru|cn|app|dev)\b)",
    re.I,
)
_EMAIL = re.compile(
    r"[^\s@]+@[^\s@]+\.[^\s@]+|\b\w+\s*\[?\(?at\)?\]?\s*\w+\s*dot\s*\w+", re.I
)
_LEET = str.maketrans("013457@$", "oieastas")


@cache
def _terms() -> dict[str, list[str]]:
    path = Path(__file__).with_name("moderation_terms.json")
    return json.loads(path.read_text("utf-8"))


def plain_text(value: object, max_len: int) -> str:
    """Plain text: no control or format characters, whitespace collapsed,
    trimmed, capped at ``max_len`` characters."""
    s = unicodedata.normalize("NFC", str(value or ""))
    s = "".join(
        " " if ch.isspace() else ch
        for ch in s
        if ch.isspace() or unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co")
    )
    return re.sub(r" +", " ", s).strip()[:max_len].strip()


def _fold(text: str) -> str:
    s = unicodedata.normalize("NFKD", text.lower())
    s = "".join(c for c in s if not unicodedata.combining(c)).translate(_LEET)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _has(folded: str, terms: list[str]) -> bool:
    padded = f" {folded} "
    return any(f" {_fold(t)} " in padded for t in terms)


def check(text: str) -> Verdict:
    if not text:
        return "allow"
    folded = _fold(text)
    if _has(folded, _terms()["reject"]):
        return "reject"
    if _has(folded, _terms()["review"]) or _URL.search(text) or _EMAIL.search(text):
        return "review"
    return "allow"


def classify(text: str) -> Verdict | None:
    """Optional classifier hook (a follow-up); None = no opinion."""
    return None
