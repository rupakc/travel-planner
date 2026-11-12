"""Trip writes over ``plans`` rows (a trip is a saved plan)."""

import json

from .database import get_connection

# Trip field → the search_data key that mirrors it, when the plan has one.
_MIRRORED = {"start_date": "departure_date", "end_date": "return_date"}
_FIELDS = ("title", "start_date", "end_date", "phase")


def create_trip(
    username: str,
    title: str,
    destination: str | None,
    start: str | None,
    end: str | None,
) -> int:
    """A new plans row: ``name = title``, ``search_data = {"destination": d}``
    (or ``{}``) and empty ``selections``. Dates live in the columns only."""
    search_data = {"destination": destination} if destination else {}
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO plans (username, name, title, search_data, selections,"
            " start_date, end_date) VALUES (?,?,?,?,?,?,?)",
            (username, title, title, json.dumps(search_data), "{}", start, end),
        )
        return cur.lastrowid


def set_trip_fields(plan_id: int, **fields) -> None:
    """Set any of ``title``, ``start_date``, ``end_date``, ``phase`` (``None``
    clears). A title also renames the plan, so older clients show it. A date
    is mirrored into ``search_data`` when the plan carries that key there, so
    the previous SPA shows the same dates and a cleared date stays cleared."""
    unknown = set(fields) - set(_FIELDS)
    if unknown:
        raise ValueError(f"unknown trip fields: {sorted(unknown)}")
    sets, vals = ["updated_at = datetime('now')"], []
    for name, value in fields.items():
        sets.append(f"{name} = ?")
        vals.append(value)
        if name == "title" and value:
            sets.append("name = ?")
            vals.append(value)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        mirrored = {_MIRRORED[k]: v for k, v in fields.items() if k in _MIRRORED}
        if mirrored:
            row = conn.execute(
                "SELECT search_data FROM plans WHERE id = ?", (plan_id,)
            ).fetchone()
            try:
                sd = json.loads(row["search_data"]) if row else None
            except ValueError:
                sd = None
            if isinstance(sd, dict) and any(k in sd for k in mirrored):
                for key, value in mirrored.items():
                    if key not in sd:
                        continue
                    if value is None:
                        sd.pop(key)
                    else:
                        sd[key] = value
                sets.append("search_data = ?")
                vals.append(json.dumps(sd))
        sql = f"UPDATE plans SET {', '.join(sets)} WHERE id = ?"  # nosec B608
        conn.execute(sql, (*vals, plan_id))
