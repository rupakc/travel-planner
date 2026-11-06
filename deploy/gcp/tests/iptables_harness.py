#!/usr/bin/env python3
"""Run the governor's real rules against real iptables (iptables-nft, as on
Debian 13) for every tier, and prove a rejected ruleset leaves the old rules
in force. Needs root + NET_ADMIN in a throwaway network namespace: run it
through deploy/gcp/tests/host_checks.sh (CI job "host-checks"), never on a
machine you care about.
"""

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "host" / "governor.py"
_spec = importlib.util.spec_from_file_location("governor", _PATH)
gov = importlib.util.module_from_spec(_spec)
sys.modules["governor"] = gov
_spec.loader.exec_module(gov)


def sh(*cmd: str) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def chain(name: str) -> list[str]:
    return [ln for ln in sh("iptables", "-S", name).splitlines() if ln.startswith("-A")]


def check(cond: bool, what: str) -> None:
    if not cond:
        print(f"FAIL: {what}")
        print(sh("iptables", "-S"))
        sys.exit(1)
    print(f"ok   {what}")


def main() -> None:
    # What Docker sets up: DOCKER-USER, jumped to from FORWARD; plus an
    # unrelated rule that the governor must never touch (--noflush)
    sh("iptables", "-N", "DOCKER-USER")
    sh("iptables", "-A", "FORWARD", "-j", "DOCKER-USER")
    sh("iptables", "-A", "FORWARD", "-s", "192.0.2.1/32", "-j", "ACCEPT")
    # One of Docker's own chains, which the governor must never touch
    sh("iptables", "-N", "DOCKER-FORWARD")
    sh("iptables", "-A", "DOCKER-FORWARD", "-o", "br-voyager", "-j", "ACCEPT")
    sh("iptables", "-A", "FORWARD", "-j", "DOCKER-FORWARD")
    docker_chain = sh("iptables", "-S", "DOCKER-FORWARD")
    # ip_forward was already 1 when dockerd started, so it left ACCEPT
    sh("iptables", "-P", "FORWARD", "ACCEPT")
    check(
        not gov.rules_in_place(gov.Config(iface="eth0")), "ACCEPT policy: not in place"
    )
    print(sh("iptables", "-V").strip())

    cfg = gov.Config(iface="eth0", state_path=Path(tempfile.mkdtemp()) / "s.json")
    for tier in ("open", "warn", "closed", "open"):
        gov.apply_rules(cfg, tier)
        guard = chain(gov.CHAIN_GUARD)
        check(
            len(guard) == 2 and "RETURN" in guard[0] and "DROP" in guard[1],
            f"[{tier}] metadata guard: RETURN for the app, then DROP",
        )
        check(len(chain(gov.CHAIN_EGRESS)) == 5, f"[{tier}] 5 egress rules")
        check(
            len(chain(gov.CHAIN_CLOSE)) == (2 if tier == "closed" else 0),
            f"[{tier}] close rules only when closed",
        )
        check(len(chain("DOCKER-USER")) == 4, f"[{tier}] 4 DOCKER-USER rules")
        check(gov.rules_in_place(cfg), f"[{tier}] every jump in place (-C)")
        check(
            "-A FORWARD -s 192.0.2.1/32 -j ACCEPT" in sh("iptables", "-S", "FORWARD"),
            f"[{tier}] unrelated rules untouched",
        )
        check(
            sh("iptables", "-S", "FORWARD").splitlines()[0] == "-P FORWARD DROP",
            f"[{tier}] FORWARD policy DROP",
        )
        check(
            sh("iptables", "-S", "DOCKER-FORWARD") == docker_chain,
            f"[{tier}] Docker's own chain untouched",
        )
    # Idempotent: applying again on a DROP policy changes nothing at all
    snapshot = sh("iptables", "-S")
    gov.apply_rules(cfg, "open")
    check(sh("iptables", "-S") == snapshot, "re-apply with DROP already set: no change")
    # Something resets the policy: no longer in place, and apply restores it
    sh("iptables", "-P", "FORWARD", "ACCEPT")
    check(not gov.rules_in_place(cfg), "policy reset to ACCEPT: rules not in place")
    gov.apply_rules(cfg, "open")
    check(
        gov.rules_in_place(cfg)
        and sh("iptables", "-S", "FORWARD").startswith("-P FORWARD DROP"),
        "apply restores FORWARD policy DROP",
    )
    check(
        "! --update-counters" in "".join(chain(gov.CHAIN_EGRESS)),
        "quota check never updates counters",
    )
    check("voyager_perip" in sh("ipset", "list", "-n"), "per-IP ipset exists")

    # A rejected ruleset must leave the previous one in force
    gov.apply_rules(cfg, "closed")
    before = sh("iptables", "-S")
    real = gov.rule_lines

    def broken(cfg, tier):
        return [*real(cfg, tier), "-A VOYAGER-EGRESS -s 10.0.0.1 -s 10.0.0.2 -j DROP"]

    gov.rule_lines = broken
    try:
        gov.apply_rules(cfg, "open")
        check(False, "a broken ruleset raises RulesError")
    except gov.RulesError as exc:
        print(f"ok   broken ruleset rejected: {str(exc)[:80]}")
    finally:
        gov.rule_lines = real
    check(sh("iptables", "-S") == before, "after a rejection the old rules are intact")
    print("ALL OK")


if __name__ == "__main__":
    main()
