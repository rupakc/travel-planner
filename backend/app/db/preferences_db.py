"""SQLite persistence for user travel preferences."""

import json

from .database import get_connection

# Traveler-composition columns added after initial release (ALTER migrations)
_COMPOSITION_COLUMNS = (
    ("adults", "INTEGER DEFAULT 1"),
    ("children", "INTEGER DEFAULT 0"),
    ("seniors", "INTEGER DEFAULT 0"),
    ("infants", "INTEGER DEFAULT 0"),
    ("accessibility_needs", "TEXT DEFAULT '[]'"),
)


def create_preferences_table() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS preferences (
                username           TEXT PRIMARY KEY,
                budget_category    TEXT DEFAULT 'medium',
                nationality        TEXT DEFAULT '',
                current_residence  TEXT DEFAULT '',
                residence_permits  TEXT DEFAULT '[]',
                existing_visas     TEXT DEFAULT '[]',
                interests          TEXT DEFAULT '[]',
                num_travelers      INTEGER DEFAULT 1,
                updated_at         TEXT DEFAULT (datetime('now'))
            );
        """)
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(preferences)").fetchall()
        }
        if "current_residence" not in cols:
            conn.execute(
                "ALTER TABLE preferences ADD COLUMN current_residence TEXT DEFAULT ''"
            )
        for name, decl in _COMPOSITION_COLUMNS:
            if name not in cols:
                conn.execute(f"ALTER TABLE preferences ADD COLUMN {name} {decl}")  # nosec B608


DEFAULT_PREFS = {
    "budget_category": "medium",
    "nationality": "",
    "current_residence": "",
    "residence_permits": [],
    "existing_visas": [],
    "interests": [],
    "num_travelers": 1,
    "adults": 1,
    "children": 0,
    "seniors": 0,
    "infants": 0,
    "accessibility_needs": [],
}


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["residence_permits"] = json.loads(d["residence_permits"])
    d["existing_visas"] = json.loads(d["existing_visas"])
    d["interests"] = json.loads(d["interests"])
    d["accessibility_needs"] = json.loads(d.get("accessibility_needs") or "[]")
    return d


def get_preferences(username: str) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM preferences WHERE username = ?", (username,)
        ).fetchone()
    if row:
        return _row_to_dict(row)
    return {"username": username, **DEFAULT_PREFS}


def save_preferences(username: str, prefs: dict) -> dict:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO preferences (username, budget_category, nationality, current_residence,
               residence_permits, existing_visas, interests, num_travelers,
               adults, children, seniors, infants, accessibility_needs, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(username) DO UPDATE SET
                   budget_category     = excluded.budget_category,
                   nationality         = excluded.nationality,
                   current_residence   = excluded.current_residence,
                   residence_permits   = excluded.residence_permits,
                   existing_visas      = excluded.existing_visas,
                   interests           = excluded.interests,
                   num_travelers       = excluded.num_travelers,
                   adults              = excluded.adults,
                   children            = excluded.children,
                   seniors             = excluded.seniors,
                   infants             = excluded.infants,
                   accessibility_needs = excluded.accessibility_needs,
                   updated_at          = datetime('now')
            """,
            (
                username,
                prefs.get("budget_category", "medium"),
                prefs.get("nationality", ""),
                prefs.get("current_residence", ""),
                json.dumps(prefs.get("residence_permits", [])),
                json.dumps(prefs.get("existing_visas", [])),
                json.dumps(prefs.get("interests", [])),
                prefs.get("num_travelers", 1),
                prefs.get("adults", 1),
                prefs.get("children", 0),
                prefs.get("seniors", 0),
                prefs.get("infants", 0),
                json.dumps(prefs.get("accessibility_needs", [])),
            ),
        )
    return get_preferences(username)
