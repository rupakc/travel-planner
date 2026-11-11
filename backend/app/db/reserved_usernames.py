"""Usernames nobody may register (they read as official or collide with routes)."""

RESERVED_USERNAMES: frozenset[str] = frozenset(
    {
        "admin", "administrator", "root", "support", "help", "voyager", "api",
        "system", "null", "undefined", "me", "account", "settings", "login",
        "signup", "verify", "auth", "share", "plans", "alerts", "moderator",
        "staff", "official",
    }
)  # fmt: skip
