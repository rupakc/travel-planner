"""Price story read model (pure, no network). Filled by Task 4."""

from datetime import datetime


def build_story(
    kind: str, watch: dict, history: list[dict], *, live_prices: bool, now: datetime
) -> dict:
    raise NotImplementedError
