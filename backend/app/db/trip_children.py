"""Shared helpers for the per-trip child tables."""

TRIP_CHILD_TABLES: tuple[str, ...] = (
    "trip_expenses",
    "trip_journal",
    "trip_ratings",
    "trip_prep",
    "trip_snapshots",
    "trip_checkins",
)


def delete_trip_children(conn, plan_id: int) -> None:
    """Delete every child row of one trip on the caller's connection."""
    for table in TRIP_CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE plan_id = ?", (plan_id,))  # nosec B608
