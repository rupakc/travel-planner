"""Daily AI quota seam (filled in by the quota task)."""

from collections.abc import Callable


def daily_quota(bucket: str) -> Callable:
    async def _dependency() -> None:
        return None

    return _dependency
