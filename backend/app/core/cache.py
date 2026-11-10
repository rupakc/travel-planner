"""The shared in-memory TTL cache (30 min by default), plus a fresh-reads mode.

Inside ``fresh_reads()`` (a manual "Check now" on a fare or price watch),
``get_cache()`` returns a view of the shared cache in which entries written
before the block are misses, so every lookup goes live; what the block
fetches is written to the shared cache as usual (refreshing it for everyone)
and is a hit for the rest of the block. Code that asks "is this cached?" to
count SerpAPI calls sees the same view, so budgets are reserved and settled
for the calls the look really makes.
"""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from cachetools import TTLCache

from .config import settings

_cache: TTLCache = TTLCache(
    maxsize=settings.cache_maxsize, ttl=settings.cache_ttl_seconds
)

# Keys written inside the current fresh_reads() block (None outside one)
_fresh: ContextVar[set | None] = ContextVar("cache_fresh_reads", default=None)


class _FreshView:
    """The shared cache, minus every entry this block hasn't written itself.

    Not a full ``TTLCache``: it supports ``in``, ``[]``, ``get``, assignment,
    ``del``, ``pop``, ``len``, iteration and ``keys`` — what the SerpAPI
    adapters use."""

    def __init__(self, cache: TTLCache, written: set) -> None:
        self._cache = cache
        self._written = written

    def __contains__(self, key: Any) -> bool:
        return key in self._written and key in self._cache

    def __getitem__(self, key: Any) -> Any:
        if key not in self._written:
            raise KeyError(key)
        return self._cache[key]

    def get(self, key: Any, default: Any = None) -> Any:
        return self[key] if key in self else default

    def __setitem__(self, key: Any, value: Any) -> None:
        self._cache[key] = value
        self._written.add(key)

    def __delitem__(self, key: Any) -> None:
        self._written.discard(key)
        del self._cache[key]

    def pop(self, key: Any, *default: Any) -> Any:
        self._written.discard(key)
        return self._cache.pop(key, *default)

    # Size and iteration agree with ``in``: only entries this block wrote
    # (and the cache still holds). Other TTLCache methods are not offered.
    def __iter__(self) -> Iterator[Any]:
        return (k for k in list(self._written) if k in self._cache)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def keys(self) -> list[Any]:
        return list(self)


def get_cache() -> TTLCache:
    written = _fresh.get()
    if written is not None:
        return _FreshView(_cache, written)  # type: ignore[return-value]
    return _cache


@contextmanager
def fresh_reads() -> Iterator[None]:
    """Within the block, cached entries are ignored (looked up live) and the
    live answers refresh the shared cache. Tasks started inside inherit it."""
    token = _fresh.set(set())
    try:
        yield
    finally:
        _fresh.reset(token)


def request_digest(request) -> str:
    """MD5 of a request model for cache keys. An absent or English ``locale``
    is left out, so English requests keep their pre-locale keys (a deploy
    doesn't invalidate the cache) while other languages get their own."""
    exclude = {"locale"} if getattr(request, "locale", None) in (None, "en") else None
    return hashlib.md5(
        request.model_dump_json(exclude=exclude).encode(), usedforsecurity=False
    ).hexdigest()
