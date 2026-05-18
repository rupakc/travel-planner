from cachetools import TTLCache

from .config import settings

_cache: TTLCache = TTLCache(
    maxsize=settings.cache_maxsize, ttl=settings.cache_ttl_seconds
)


def get_cache() -> TTLCache:
    return _cache
