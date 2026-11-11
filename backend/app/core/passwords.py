"""Password policy: length bounds, common-password list, identity match.

The common-password list (data/common_passwords.txt) is the 10,000 most
common passwords from SecLists, Passwords/Common-Credentials/10k-most-common.txt
(https://github.com/danielmiessler/SecLists), released under the MIT licence,
Copyright (c) 2018 Daniel Miessler.
"""

from functools import lru_cache
from pathlib import Path

MIN_PASSWORD_LENGTH_V2 = 10
MAX_PASSWORD_LENGTH = 128

_LIST_PATH = Path(__file__).parent / "data" / "common_passwords.txt"


@lru_cache(maxsize=1)
def _common() -> frozenset[str]:
    text = _LIST_PATH.read_text(encoding="utf-8", errors="ignore")
    return frozenset(line.strip().lower() for line in text.splitlines() if line.strip())


def password_problem(
    password: str, *, username: str | None = None, email: str | None = None
) -> str | None:
    """Return an error code for a rejected password, or None if acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH_V2:
        return "password_too_short"
    if len(password) > MAX_PASSWORD_LENGTH:
        return "password_too_long"
    lowered = password.lower()
    common = _common()
    if lowered in common:
        return "password_common"
    # A common word with up to four trailing digits ("password12") is as weak.
    base = lowered.rstrip("0123456789")
    if len(base) >= 4 and len(lowered) - len(base) <= 4 and base in common:
        return "password_common"
    identities = set()
    for value in (username, email):
        if value and value.strip():
            v = value.strip().lower()
            identities.add(v)
            if "@" in v:
                identities.add(v.split("@", 1)[0])
    if lowered in identities:
        return "password_matches_identity"
    return None
