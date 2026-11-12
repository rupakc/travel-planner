"""Deal-hunter game hooks for price alerts. Bodies filled by Task 5."""


def on_drop(
    user_id: str,
    watch_kind: str,
    watch_id: int,
    notification_id: int,
    facts: dict,
) -> dict | None:
    return None


def on_savings(user_id: str, total_usd: float) -> dict | None:
    return None
