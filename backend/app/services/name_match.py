"""Shared name ↔ search-result title matching.

Used by hotel URL enrichment (`_URLSearchMixin._search_url`) and by the
activity/place resolvers to decide whether a search result is really about
the named item. Matching uses word overlap on distinctive words (common /
stop words filtered out): short names (1-2 distinctive words) need every
word, longer names need at least half with a floor of 2.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

STOP_WORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "tour",
        "tours",
        "with",
        "from",
        "hotel",
        "hotels",
        "book",
        "booking",
        "tickets",
        "city",
        "best",
        "top",
        "guide",
        "travel",
        "trip",
        "official",
        "site",
        "website",
        "new",
        "york",
        "los",
        "angeles",
        "san",
        "francisco",
        "airline",
        "airlines",
        "international",
        "airways",
        "air",
        "lines",
    }
)


def words(text: str) -> set[str]:
    """Lower-cased alphanumeric words longer than 2 characters."""
    clean = re.sub(r"[^a-zA-Z0-9\s]", " ", text or "").lower()
    return {w for w in clean.split() if len(w) > 2}


def distinctive_words(name: str, exclude: Iterable[str] = ()) -> set[str]:
    """Distinctive words of ``name``.

    Stop words are dropped (falling back to all words when only stop words
    remain); then any ``exclude`` words (e.g. destination tokens) are removed.
    May return an empty set — callers must treat that as "cannot match".
    """
    all_words = words(name)
    name_words = all_words - STOP_WORDS
    if not name_words:
        name_words = all_words
    excluded: set[str] = set()
    for item in exclude:
        excluded |= words(item)
    return name_words - excluded


def min_matches(name_words: set[str]) -> int:
    """Short names (1-2 words) need all words; longer need half, floor 2."""
    if len(name_words) <= 2:
        return len(name_words)
    return max(2, len(name_words) // 2)


def match_score(name_words: set[str], text: str) -> int:
    return len(name_words & words(text))


def name_matches_title(name: str, title: str, exclude: Iterable[str] = ()) -> bool:
    """True when ``name``'s distinctive words appear in ``title``."""
    name_words = distinctive_words(name, exclude)
    if not name_words or not title:
        return False
    return match_score(name_words, title) >= min_matches(name_words)
