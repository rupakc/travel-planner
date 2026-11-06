#!/usr/bin/env python3
"""Strip the old-prod export (886 MB) down to the users and their own data.

The 2026-08-30 export of the decommissioned project
(~/gcp-decommission-export-20260830/.../sqlite-backups/airports.db) is a
full DB: airports, nationalities and a sqlite_sequence of ~42 M rows (that's
the size), around a few KB of user data. This tool:

1. opens the export strictly read-only (``mode=ro&immutable=1``, so not even
   a -shm is created) and hashes it before and after to prove it;
2. creates a new DB with the **current** app schema (the app's own
   ``create_*_table`` functions, in a subprocess with a scratch DATA_DIR);
3. copies the user tables: users, plans, preferences, taste_signals,
   recent_searches, feedback — named columns both schemas share (columns the
   app dropped are reported with their non-null counts);
4. collapses sqlite_sequence to one row per table at its true maximum, so
   ids are never reused;
5. verifies per-table row counts, runs integrity_check, VACUUMs, and writes
   ``migration-report.md`` / ``.json`` next to the output (counts only, no
   user data).

The result has no place data and no place-data version, so the app reseeds
it at first start. Put it on the VM's data disk as
/var/lib/voyager/data/airports.db before the first start, or upload it as
gs://<bucket>/sqlite-backups/airports.db so restore-if-missing picks it up
(docs/Deployment-GCP.md).

Usage: migrate_old_prod.py [--export PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess  # nosec B404 — fixed argv, our own interpreter
import sys
import tempfile
from pathlib import Path

DEFAULT_EXPORT = (
    Path.home()
    / "gcp-decommission-export-20260830"
    / "gen-lang-client-0157695995-sqlite-backup"
    / "sqlite-backups"
    / "airports.db"
)
USER_TABLES = (
    "users",
    "plans",
    "preferences",
    "taste_signals",
    "recent_searches",
    "feedback",
)
BACKEND = Path(__file__).resolve().parents[2] / "backend"

_SCHEMA_SNIPPET = """
from app.db.users_db import create_users_table
from app.db.plans_db import create_plans_table
from app.db.preferences_db import create_preferences_table
from app.db.taste_db import create_taste_table
from app.db.feedback_db import create_feedback_table
from app.db.recent_searches_db import create_recent_searches_table
for f in (create_users_table, create_plans_table, create_preferences_table,
          create_taste_table, create_feedback_table, create_recent_searches_table):
    f()
"""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _ro_uri(path: Path) -> str:
    return f"file:{path.resolve()}?mode=ro&immutable=1"


def _count(conn: sqlite3.Connection, schema: str, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {schema}.{_q(table)}").fetchone()[0]  # nosec B608


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({_q(table)})")]


def _tables(conn: sqlite3.Connection, schema: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table'"  # nosec B608
        )
    }


def build_schema(db_path: Path) -> None:
    """Create the current app schema for the user tables in ``db_path``."""
    with tempfile.TemporaryDirectory() as data_dir:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(BACKEND),
            "DATA_DIR": data_dir,
            "LOG_FORMAT": "text",
            "ADMIN_PASSWORD": "",
            "JWT_SECRET_KEY": "schema-only",
        }
        # cwd = the scratch dir, so no .env file is ever read
        subprocess.run(  # nosec B603
            [sys.executable, "-c", _SCHEMA_SNIPPET],
            cwd=data_dir,
            env=env,
            check=True,
            capture_output=True,
        )
        os.replace(Path(data_dir) / "airports.db", db_path)


def migrate(export: Path, out: Path) -> dict:
    export = Path(export)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    before = sha256(export)
    tmp = out.with_name(out.name + ".building")
    tmp.unlink(missing_ok=True)
    build_schema(tmp)

    conn = sqlite3.connect(str(tmp), uri=True)
    rows = []
    ok = True
    try:
        conn.execute("ATTACH DATABASE ? AS old", (_ro_uri(export),))
        old_tables = _tables(conn, "old")
        new_tables = _tables(conn, "main")
        for table in USER_TABLES:
            entry = {"table": table}
            if table not in new_tables:
                entry.update(status="not in current schema", ok=False)
                ok = False
            elif table not in old_tables:
                entry.update(status="absent in export", old_rows=0, new_rows=0, ok=True)
            else:
                new_cols = _columns(conn, "main", table)
                old_cols = _columns(conn, "old", table)
                shared = [c for c in old_cols if c in new_cols]
                dropped = {
                    c: conn.execute(
                        f"SELECT COUNT(*) FROM old.{_q(table)} WHERE {_q(c)} IS NOT NULL"  # nosec B608
                    ).fetchone()[0]
                    for c in old_cols
                    if c not in new_cols
                }
                cols = ", ".join(_q(c) for c in shared)
                conn.execute(
                    f"INSERT INTO main.{_q(table)} ({cols}) "  # nosec B608
                    f"SELECT {cols} FROM old.{_q(table)}"
                )
                old_n = _count(conn, "old", table)
                new_n = _count(conn, "main", table)
                good = old_n == new_n
                ok &= good
                entry.update(
                    status="copied" if good else "COUNT MISMATCH",
                    old_rows=old_n,
                    new_rows=new_n,
                    dropped_columns=dropped,
                    ok=good,
                )
            rows.append(entry)

        # sqlite_sequence: one row per table at max(old counters, max id)
        seq = {}
        if "sqlite_sequence" in old_tables:
            names = [r["table"] for r in rows if r.get("status") == "copied"]
            marks = ",".join("?" * len(names))
            if names:
                seq = dict(
                    conn.execute(
                        "SELECT name, MAX(seq) FROM old.sqlite_sequence "  # nosec B608
                        f"WHERE name IN ({marks}) GROUP BY name",
                        names,
                    ).fetchall()
                )
        if "sqlite_sequence" in _tables(conn, "main"):
            for (name,) in conn.execute(
                "SELECT name FROM main.sqlite_sequence"
            ).fetchall():
                seq.setdefault(name, 0)
            for name in list(seq):
                if "id" in _columns(conn, "main", name):
                    top = conn.execute(
                        f"SELECT MAX(id) FROM main.{_q(name)}"
                    ).fetchone()[0]  # nosec B608
                    if isinstance(top, int):  # non-integer ids (uuids) have no counter
                        seq[name] = max(seq[name] or 0, top)
            conn.execute("DELETE FROM main.sqlite_sequence")
            conn.executemany(
                "INSERT INTO main.sqlite_sequence (name, seq) VALUES (?, ?)",
                sorted(seq.items()),
            )
        conn.commit()
        conn.execute("DETACH DATABASE old")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        ok &= integrity == "ok"
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("VACUUM")
    finally:
        conn.close()

    after = sha256(export)
    ok &= before == after
    os.replace(tmp, out)
    return {
        "ok": bool(ok),
        "export": str(export),
        "export_bytes": export.stat().st_size,
        "export_sha256_before": before,
        "export_sha256_after": after,
        "output": str(out),
        "output_bytes": out.stat().st_size,
        "integrity_check": integrity,
        "sqlite_sequence": seq,
        "tables": rows,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Old-prod migration report",
        "",
        f"- Result: **{'OK' if report['ok'] else 'FAILED'}**",
        f"- Export: `{report['export']}` ({report['export_bytes']:,} bytes)",
        f"- Export SHA-256 before: `{report['export_sha256_before']}`",
        (
            f"- Export SHA-256 after:  `{report['export_sha256_after']}` (unchanged: "
            f"{report['export_sha256_before'] == report['export_sha256_after']})"
        ),
        f"- Output: `{report['output']}` ({report['output_bytes']:,} bytes)",
        f"- integrity_check: {report['integrity_check']}",
        "",
        "| Table | Status | Export rows | Migrated rows | Dropped columns (non-null) |",
        "|---|---|---:|---:|---|",
    ]
    for r in report["tables"]:
        dropped = ", ".join(
            f"{k} ({v})" for k, v in (r.get("dropped_columns") or {}).items()
        )
        lines.append(
            f"| {r['table']} | {r['status']} | {r.get('old_rows', '')} | "
            f"{r.get('new_rows', '')} | {dropped or '-'} |"
        )
    lines += [
        "",
        "AUTOINCREMENT counters kept: "
        + (
            ", ".join(f"{k}={v}" for k, v in sorted(report["sqlite_sequence"].items()))
            or "-"
        ),
        "",
        (
            "Not migrated (regenerated or new since): airports, nationalities, "
            "place data, price/fare watches, notifications, devices."
        ),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--export", type=Path, default=DEFAULT_EXPORT)
    p.add_argument("--out", type=Path, default=Path("migration") / "airports.db")
    args = p.parse_args(argv)
    if not args.export.is_file():
        sys.exit(f"export not found: {args.export}")
    if args.out.exists():
        sys.exit(f"refusing to overwrite {args.out}")
    if args.out.resolve() == args.export.resolve() or args.out.resolve().is_relative_to(
        args.export.resolve().parent
    ):
        sys.exit("the output must not be written next to the export")
    report = migrate(args.export, args.out)
    (args.out.parent / "migration-report.json").write_text(json.dumps(report, indent=2))
    (args.out.parent / "migration-report.md").write_text(render_markdown(report))
    print(render_markdown(report))
    if not report["ok"]:
        sys.exit("migration FAILED: see the report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
