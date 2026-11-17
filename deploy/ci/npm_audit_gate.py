#!/usr/bin/env python3
"""Fail CI on HIGH/CRITICAL npm advisories, except owner-approved, expiring allowlist entries.

Usage: npm audit --json | python3 deploy/ci/npm_audit_gate.py [--allowlist FILE] [--today YYYY-MM-DD]

`npm audit --json` reports a package as vulnerable when any dependency below it is, so a
package's own severity says little. This walks every package's `via` chain down to the
advisories themselves and judges those: the gate fails when any HIGH or CRITICAL advisory is
not on the allowlist, or its allowlist entry has expired (an expired entry counts as absent,
so the check turns red again on its own). Moderate and low advisories never fail it, as
before. Allowlist entries no longer reported are printed so they can be removed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

FAILING = {"high", "critical"}
DEFAULT_ALLOWLIST = Path(__file__).with_name("npm-audit-allowlist.json")


def advisories(report: dict) -> dict[str, dict]:
    """Every advisory in the report, keyed by its GHSA id (from the advisory URL)."""
    out: dict[str, dict] = {}
    for pkg, vuln in (report.get("vulnerabilities") or {}).items():
        for via in vuln.get("via") or []:
            if isinstance(via, dict):
                gid = str(via.get("url", "")).rstrip("/").rsplit("/", 1)[-1] or str(via.get("source"))
                entry = out.setdefault(gid, {"severity": via.get("severity", ""), "packages": set()})
                entry["packages"].add(pkg)
    return out


def load_allowlist(path: Path, today: dt.date) -> tuple[dict[str, dict], list[str]]:
    """Active entries by id, plus messages about expired ones."""
    active: dict[str, dict] = {}
    notes: list[str] = []
    for e in json.loads(path.read_text()):
        expires = dt.date.fromisoformat(e["expires"])
        if not e.get("reason") or not e.get("approved_by"):
            raise SystemExit(f"allowlist entry {e.get('id')} needs a reason and approved_by")
        if expires < today:
            notes.append(f"EXPIRED allowlist entry {e['id']} (expired {e['expires']}): it fails again")
        else:
            active[e["id"]] = e
    return active, notes


def gate(report: dict, allow: dict[str, dict]) -> tuple[list[str], list[str]]:
    """(failures, info lines)."""
    found = advisories(report)
    failures, info = [], []
    for gid, a in sorted(found.items()):
        if a["severity"] not in FAILING:
            continue
        pkgs = ", ".join(sorted(a["packages"]))
        if gid in allow:
            info.append(f"allowed {gid} ({a['severity']}, {pkgs}) until {allow[gid]['expires']}: {allow[gid]['reason']}")
        else:
            failures.append(f"{gid} ({a['severity']}) in {pkgs}: https://github.com/advisories/{gid}")
    for gid in sorted(set(allow) - set(found)):
        info.append(f"allowlist entry {gid} is no longer reported: remove it")
    return failures, info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    ap.add_argument("--today", type=dt.date.fromisoformat, default=dt.datetime.now(dt.timezone.utc).date())
    args = ap.parse_args(argv)
    report = json.load(sys.stdin)
    allow, notes = load_allowlist(args.allowlist, args.today)
    failures, info = gate(report, allow)
    for line in notes + info:
        print(line)
    for line in failures:
        print(f"FAIL {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
