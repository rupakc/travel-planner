"""Operator tool: set a user's password, or create an admin, from a shell.

    python -m app.set_password USERNAME              # reset an existing user
    python -m app.set_password USERNAME --create --admin   # new admin

The password is read twice with ``getpass`` (no echo, never an argument, so it
stays out of shell history, ``ps`` and logs). A reset also reactivates the
account and clears the forced-change flag: the operator chose the password.
On the production VM run it inside the app container (docs/Deployment-GCP.md):

    sudo docker exec -it voyager-app-1 python -m app.set_password admin
"""

from __future__ import annotations

import argparse
import getpass
import sys

from .core.auth import MIN_PASSWORD_LENGTH
from .db import users_db


def _read_password() -> str | None:
    first = getpass.getpass("New password: ")
    if len(first) < MIN_PASSWORD_LENGTH:
        print(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            file=sys.stderr,
        )
        return None
    if getpass.getpass("Repeat it: ") != first:
        print("The two passwords don't match.", file=sys.stderr)
        return None
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.set_password", description=__doc__.split("\n")[0]
    )
    parser.add_argument("username")
    parser.add_argument(
        "--create", action="store_true", help="create the user (fails if it exists)"
    )
    parser.add_argument(
        "--admin", action="store_true", help="with --create: make the user an admin"
    )
    args = parser.parse_args(argv)

    existing = users_db.get_user_by_username(args.username)
    if args.create and existing:
        print(
            f"User '{args.username}' already exists; run without --create to reset it.",
            file=sys.stderr,
        )
        return 1
    if not args.create and not existing:
        print(
            f"No user '{args.username}'. Add --create (and --admin) to make one.",
            file=sys.stderr,
        )
        return 1

    password = _read_password()
    if password is None:
        return 1

    if args.create:
        users_db.create_user(
            args.username, password, is_admin=args.admin, is_first_login=False
        )
        role = "admin" if args.admin else "user"
        print(f"Created {role} '{args.username}'.")
    else:
        users_db.change_password(args.username, password)
        users_db.reactivate_user(args.username)
        print(f"Password set for '{args.username}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
