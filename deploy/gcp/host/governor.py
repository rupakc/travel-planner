#!/usr/bin/env python3
"""Voyager egress governor: keeps the VM inside the free 200 GiB/month of
Standard-tier egress, on the box, without waiting for billing data.

Layers (design §2.2 + §13 item 9):
  always    per destination IP: ≈ 4 Mbit/s (hashlimit) and ≈ 3 GiB/day
            (ipset byte counter, 24 h element timeout), plus a tc shaper at
            50 Mbit/s on the NIC;
  150 GiB   email warning, shaper down to 20 Mbit/s;
  200 GiB   close 80/443 until the billing month resets (00:00
            America/Los_Angeles) or an operator reopens (``reopen``).

Rules live in Docker's DOCKER-USER chain (which the governor owns) and are
replaced in one iptables-restore transaction, validated first, so a bad rule
can never leave the box without rules: published ports are DNAT'd and go
through FORWARD, so an INPUT rule would never see them. Docker rewrites its
own chains when it starts, so ``apply`` runs after every docker start
(voyager-governor-rules.service) and on every tick.

The month-to-date counter adds per-minute deltas of the NIC's tx_bytes (a
superset of billable egress: Google API and same-region traffic are free
but counted, so it errs towards closing early). It is reboot-safe: a new
boot id or a counter that went backwards counts the new raw value as the
delta. State is persisted atomically every tick.

Usage: governor.py tick | apply | status | reopen [--extra-gib N]
                   | seed --gib N | close | mail --subject S --body B
Config: /etc/voyager/governor.env (KEY=VALUE, optional).

The pure functions (month_key, apply_tick, decide, render_restore, ...) are
unit-tested in deploy/gcp/tests/test_governor.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import smtplib
import subprocess  # nosec B404 — fixed argv lists, no shell
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

GiB = 1024**3
BILLING_TZ = ZoneInfo("America/Los_Angeles")
CHAIN_EGRESS = "VOYAGER-EGRESS"
CHAIN_CLOSE = "VOYAGER-CLOSE"
CHAIN_GUARD = "VOYAGER-GUARD"
METADATA_IP = "169.254.169.254"
CONFIG_FILE = Path("/etc/voyager/governor.env")
METADATA = "http://metadata.google.internal/computeMetadata/v1"

log = logging.getLogger("voyager-governor")


class StateError(RuntimeError):
    pass


@dataclass
class Config:
    warn_bytes: int = 150 * GiB
    close_bytes: int = 200 * GiB
    per_ip_daily_bytes: int = 3 * GiB
    per_ip_rate: str = "500kb/s"  # bytes: ≈ 4 Mbit/s
    per_ip_burst: str = "2mb"
    base_mbit: int = 50
    warn_mbit: int = 20
    iface: str = "ens4"
    bridge: str = "br-voyager"
    ports: str = "80,443"
    ipset: str = "voyager_perip"
    subnet: str = "172.30.0.0/24"  # compose network
    app_ip: str = "172.30.0.10"  # the only container allowed to reach metadata
    state_path: Path = Path("/var/lib/voyager/governor/state.json")
    smtp: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> Config:
        env = {}
        if path.is_file():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"')
        cfg = cls()
        if "GOVERNOR_WARN_GIB" in env:
            cfg.warn_bytes = int(float(env["GOVERNOR_WARN_GIB"]) * GiB)
        if "GOVERNOR_CLOSE_GIB" in env:
            cfg.close_bytes = int(float(env["GOVERNOR_CLOSE_GIB"]) * GiB)
        if "GOVERNOR_IFACE" in env:
            cfg.iface = env["GOVERNOR_IFACE"]
        else:
            cfg.iface = default_iface() or cfg.iface
        if "GOVERNOR_STATE" in env:
            cfg.state_path = Path(env["GOVERNOR_STATE"])
        cfg.smtp = {k: v for k, v in env.items() if k.startswith(("SMTP_", "ALERT_"))}
        return cfg


# ── Pure logic ─────────────────────────────────────────────────────────────


def month_key(now: float) -> str:
    """Google's billing month: calendar month in US Pacific time."""
    return datetime.fromtimestamp(now, BILLING_TZ).strftime("%Y-%m")


def new_state(month: str, raw: int, boot_id: str) -> dict:
    return {
        "month": month,
        "total": 0,
        "last_raw": raw,
        "boot_id": boot_id,
        "warned": False,
        "closed": False,
        "close_at": None,
        "applied_rate": None,
        "applied_tier": None,
        "updated": None,
    }


def apply_tick(state: dict, raw: int, boot_id: str, now: float) -> dict:
    s = dict(state)
    if boot_id != s.get("boot_id") or raw < s.get("last_raw", 0):
        delta = raw  # counter restarted (reboot, driver reset)
    else:
        delta = raw - s["last_raw"]
    month = month_key(now)
    if month != s["month"]:
        s.update(month=month, total=0, warned=False, closed=False, close_at=None)
    s["total"] += delta
    s["last_raw"] = raw
    s["boot_id"] = boot_id
    s["updated"] = now
    return s


@dataclass
class Decision:
    tier: str  # open | warn | closed
    rate_mbit: int
    notify: str | None  # None | "warn" | "close"


def decide(state: dict, cfg: Config) -> Decision:
    total = state["total"]
    close_at = state.get("close_at") or cfg.close_bytes
    if total >= close_at:
        return Decision("closed", cfg.warn_mbit, None if state["closed"] else "close")
    if total >= cfg.warn_bytes:
        return Decision("warn", cfg.warn_mbit, None if state["warned"] else "warn")
    return Decision("open", cfg.base_mbit, None)


def record(state: dict, d: Decision) -> dict:
    s = dict(state)
    if d.tier in ("warn", "closed"):
        s["warned"] = True
    s["closed"] = d.tier == "closed"
    return s


def reopen(state: dict, extra_bytes: int) -> dict:
    """Operator accepts overage (≈ $0.085/GiB): close again after
    ``extra_bytes`` more this month."""
    s = dict(state)
    s["close_at"] = s["total"] + extra_bytes
    s["closed"] = False
    return s


def seed(state: dict, at_least: int) -> dict:
    """After a disk restore: take the larger of our total and Monitoring's
    month-to-date sent bytes (or a safe guess such as 150 GiB)."""
    s = dict(state)
    s["total"] = max(s["total"], at_least)
    return s


def _ipt(*args: str) -> list[str]:
    return ["iptables", "-w", "5", *args]


class RulesError(RuntimeError):
    """The new ruleset was rejected; the previous rules are still in force."""


def rule_lines(cfg: Config, tier: str) -> list[str]:
    """The governor's rules in iptables-restore syntax (filter table)."""
    ports = cfg.ports
    lines = [
        # Only the app may reach the metadata server (ADC for Gemini, Secret
        # Manager, GCS, FCM); a compromised Caddy gets no VM tokens.
        # (iptables allows one -s per rule: RETURN the app, then DROP the rest.)
        f"-A {CHAIN_GUARD} -s {cfg.app_ip}/32 -d {METADATA_IP}/32 -j RETURN",
        f"-A {CHAIN_GUARD} -i {cfg.bridge} -s {cfg.subnet} -d {METADATA_IP}/32 -j DROP",
        # Per destination IP (the client our web server is sending to):
        # remember it for 24 h (first packet starts the day), count its bytes
        # exactly once (the counting rule), drop above the daily quota (the
        # check never updates counters), and above ≈ 4 Mbit/s
        f"-A {CHAIN_EGRESS} -j SET --add-set {cfg.ipset} dst",
        f"-A {CHAIN_EGRESS} -m set --match-set {cfg.ipset} dst",
        (
            f"-A {CHAIN_EGRESS} -m set --match-set {cfg.ipset} dst ! --update-counters"
            f" --bytes-gt {cfg.per_ip_daily_bytes} -j DROP"
        ),
        (
            f"-A {CHAIN_EGRESS} -m hashlimit --hashlimit-mode dstip"
            f" --hashlimit-name voyager_rate --hashlimit-above {cfg.per_ip_rate}"
            f" --hashlimit-burst {cfg.per_ip_burst} --hashlimit-htable-expire 120000"
            f" --hashlimit-htable-max 65536 -j DROP"
        ),
        f"-A {CHAIN_EGRESS} -j RETURN",
    ]
    lines += close_rules(cfg, closed=tier == "closed")
    # DOCKER-USER is the governor's: Docker never puts its own rules there
    lines += [
        f"-A DOCKER-USER -j {CHAIN_GUARD}",
        f"-A DOCKER-USER -j {CHAIN_CLOSE}",
        # Egress: Caddy's replies leaving the bridge for the internet
        (
            f"-A DOCKER-USER -i {cfg.bridge} -o {cfg.iface} -p tcp -m multiport"
            f" --sports {ports} -j {CHAIN_EGRESS}"
        ),
        "-A DOCKER-USER -j RETURN",
    ]
    return lines


def render_restore(cfg: Config, tier: str) -> str:
    """One iptables-restore transaction (``--noflush``: other chains and
    tables are untouched; the chains declared here are flushed and refilled
    in the same commit, so traffic never sees a half-built ruleset)."""
    chains = ["DOCKER-USER", CHAIN_GUARD, CHAIN_CLOSE, CHAIN_EGRESS]
    return (
        "*filter\n"
        + "".join(f":{c} - [0:0]\n" for c in chains)
        + "".join(line + "\n" for line in rule_lines(cfg, tier))
        + "COMMIT\n"
    )


def ipset_command(cfg: Config) -> list[str]:
    return ["ipset", "create", cfg.ipset, "hash:ip", "timeout", "86400",
            "counters", "-exist"]  # fmt: skip


def jump_specs(cfg: Config) -> list[list[str]]:
    return [
        ["-j", CHAIN_GUARD],
        ["-j", CHAIN_CLOSE],
        ["-i", cfg.bridge, "-o", cfg.iface, "-p", "tcp", "-m", "multiport",
         "--sports", cfg.ports, "-j", CHAIN_EGRESS],
    ]  # fmt: skip


def close_rules(cfg: Config, closed: bool) -> list[str]:
    if not closed:
        return []
    return [
        (
            f"-A {CHAIN_CLOSE} -i {cfg.iface} -o {cfg.bridge} -p tcp -m multiport"
            f" --dports {cfg.ports} -j DROP"
        ),
        (
            f"-A {CHAIN_CLOSE} -i {cfg.bridge} -o {cfg.iface} -p tcp -m multiport"
            f" --sports {cfg.ports} -j DROP"
        ),
    ]


def tc_command(cfg: Config, rate_mbit: int) -> list[str]:
    return ["tc", "qdisc", "replace", "dev", cfg.iface, "root", "tbf",
            "rate", f"{rate_mbit}mbit", "burst", "256kb", "latency", "400ms"]  # fmt: skip


_IPSET_ADD = re.compile(r"^add \S+ (\S+) .*\bbytes (\d+)")


def top_talkers(ipset_save: str, n: int = 10) -> list[tuple[str, int]]:
    rows = []
    for line in ipset_save.splitlines():
        m = _IPSET_ADD.match(line.strip())
        if m:
            rows.append((m.group(1), int(m.group(2))))
    return sorted(rows, key=lambda r: -r[1])[:n]


def status_json(state: dict, cfg: Config) -> str:
    d = decide(state, cfg)
    return json.dumps(
        {
            "month": state["month"],
            "tier": d.tier,
            "total_gib": round(state["total"] / GiB, 3),
            "warn_gib": cfg.warn_bytes / GiB,
            "close_gib": (state.get("close_at") or cfg.close_bytes) / GiB,
            "rate_mbit": d.rate_mbit,
        }
    )


# ── Persistence ────────────────────────────────────────────────────────────


def load_state(path: Path) -> dict | None:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    try:
        return json.loads(text)
    except ValueError as exc:
        # Never reset silently: a lost counter could hide 200 GiB
        raise StateError(f"{path}: corrupt state ({exc}); fix or seed it") from exc


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


# ── Side effects (host only) ───────────────────────────────────────────────


def run(
    cmd: list[str], check: bool = True, input: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(  # nosec B603
        cmd, check=check, capture_output=True, text=True, input=input
    )


def default_iface() -> str | None:
    try:
        out = run(["ip", "-o", "route", "show", "default"], check=False).stdout
    except FileNotFoundError:
        return None
    m = re.search(r"\bdev (\S+)", out)
    return m.group(1) if m else None


def read_raw(cfg: Config) -> int:
    return int(Path(f"/sys/class/net/{cfg.iface}/statistics/tx_bytes").read_text())


def read_boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def wait_for_docker_user(timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while run(_ipt("-L", "DOCKER-USER", "-n"), check=False).returncode != 0:
        if time.time() > deadline:
            raise RuntimeError("DOCKER-USER chain missing: is docker running?")
        time.sleep(2)


def apply_rules(cfg: Config, tier: str) -> None:
    """Replace the governor's rules atomically. The ruleset is checked with
    ``iptables-restore --test`` and then committed in one transaction; on
    any error RulesError is raised and the previous rules stay in force."""
    wait_for_docker_user()
    r = run(ipset_command(cfg), check=False)
    if r.returncode:
        raise RulesError(f"ipset create failed: {r.stderr.strip()}")
    text = render_restore(cfg, tier)
    for extra in (["--test"], []):
        r = run(["iptables-restore", "-w", "5", "--noflush", *extra], check=False,
                input=text)  # fmt: skip
        if r.returncode:
            step = "validation" if extra else "commit"
            raise RulesError(f"iptables-restore {step} failed: {r.stderr.strip()}")


def rules_in_place(cfg: Config) -> bool:
    """Every jump into our chains is present in DOCKER-USER (Docker may have
    rebuilt its chains)."""
    return all(
        run(_ipt("-C", "DOCKER-USER", *spec), check=False).returncode == 0
        for spec in jump_specs(cfg)
    )


def apply_rate(cfg: Config, state: dict, rate: int) -> dict:
    if state.get("applied_rate") != rate:
        run(tc_command(cfg, rate))
        state = dict(state, applied_rate=rate)
    return state


def _metadata(path: str) -> str:
    req = urllib.request.Request(
        f"{METADATA}/{path}", headers={"Metadata-Flavor": "Google"}
    )
    with urllib.request.urlopen(req, timeout=5) as r:  # nosec B310 — fixed URL
        return r.read().decode()


def _secret(name: str) -> str:
    import base64

    token = json.loads(_metadata("instance/service-accounts/default/token"))
    project = _metadata("project/project-id")
    url = (
        f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets/"
        f"{name}/versions/latest:access"
    )
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token['access_token']}"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:  # nosec B310 — fixed host
        return base64.b64decode(json.load(r)["payload"]["data"]).decode().rstrip("\r\n")


def send_email(cfg: Config, subject: str, body: str) -> bool:
    """SMTP submission on 587 (port 25 is blocked on GCE). Best effort."""
    smtp = cfg.smtp
    if not smtp.get("SMTP_HOST") or not smtp.get("ALERT_TO"):
        log.warning("No SMTP_HOST/ALERT_TO in %s: email skipped", CONFIG_FILE)
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = smtp.get("SMTP_FROM") or smtp.get("SMTP_USERNAME", "")
        msg["To"] = smtp["ALERT_TO"]
        msg.set_content(body)
        with smtplib.SMTP(smtp["SMTP_HOST"], int(smtp.get("SMTP_PORT", "587")),
                          timeout=20) as s:  # fmt: skip
            s.starttls()
            if smtp.get("SMTP_USERNAME"):
                password = _secret(smtp.get("SMTP_PASSWORD_SECRET", "smtp-password"))
                s.login(smtp["SMTP_USERNAME"], password)
            s.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("Email failed: %s: %s", type(exc).__name__, exc)
        return False


def _talkers_text(cfg: Config) -> str:
    out = run(["ipset", "save", cfg.ipset], check=False).stdout
    rows = top_talkers(out)
    return (
        "\n".join(f"  {ip:<40} {b / GiB:8.3f} GiB (24 h)" for ip, b in rows)
        or "  (none)"
    )


def notify(cfg: Config, state: dict, kind: str) -> None:
    talkers = _talkers_text(cfg)
    gib = state["total"] / GiB
    if kind == "warn":
        subject = f"[voyager] egress warning: {gib:.1f} GiB this month"
        body = (
            f"Month-to-date egress is {gib:.1f} GiB (warning at "
            f"{cfg.warn_bytes / GiB:.0f}, ports close at "
            f"{(state.get('close_at') or cfg.close_bytes) / GiB:.0f}). "
            "The shaper is now at 20 Mbit/s.\n"
        )
    else:
        subject = f"[voyager] ports 80/443 CLOSED at {gib:.1f} GiB"
        body = (
            f"Month-to-date egress reached {gib:.1f} GiB, so the site is closed "
            "until 00:00 America/Los_Angeles on the 1st. To reopen and accept "
            "overage ($0.085/GiB): sudo /opt/voyager/governor.py reopen "
            "--extra-gib 20\n"
        )
    body += f"\nTop destination IPs:\n{talkers}\n"
    log.warning("%s\n%s", subject, body)
    send_email(cfg, subject, body)


def _state_for_now(cfg: Config) -> dict:
    state = load_state(cfg.state_path)
    if state is None:
        state = new_state(month_key(time.time()), read_raw(cfg), read_boot_id())
    return state


def cmd_tick(cfg: Config) -> None:
    state = apply_tick(_state_for_now(cfg), read_raw(cfg), read_boot_id(), time.time())
    save_state(cfg.state_path, state)  # counted bytes survive any failure below
    d = decide(state, cfg)
    failure = None
    # Rebuild only on a tier change or when Docker dropped our jumps: a flush
    # would reset every client's rate bucket (hashlimit) each minute
    if state.get("applied_tier") != d.tier or not rules_in_place(cfg):
        try:
            apply_rules(cfg, d.tier)
            state = dict(state, applied_tier=d.tier)
        except RulesError as exc:
            # Old rules stay in force (atomic restore); shaping and the
            # threshold emails below still run, then the unit fails loudly
            failure = str(exc)
            log.error("Governor rules not applied: %s", failure)
    state = rules_alert(cfg, state, failure)
    state = apply_rate(cfg, state, d.rate_mbit)
    if d.notify:
        notify(cfg, state, d.notify)
    state = record(state, d)
    save_state(cfg.state_path, state)
    print(status_json(state, cfg))
    if failure:
        raise RulesError(failure)


def rules_alert(cfg: Config, state: dict, failure: str | None) -> dict:
    """Email once when the rules start failing, and once when they recover."""
    before = state.get("rules_error")
    if failure and not before:
        send_email(
            cfg,
            "[voyager] egress governor rules FAILED to apply",
            f"The new ruleset was rejected; the previous rules are still in "
            f"force (tier {state.get('applied_tier')}).\n\n{failure}\n\n"
            "Check: journalctl -u voyager-governor; sudo iptables -S DOCKER-USER\n",
        )
    elif before and not failure:
        send_email(cfg, "[voyager] egress governor rules applied again", "Recovered.\n")
    return dict(state, rules_error=failure)


def cmd_apply(cfg: Config) -> None:
    state = _state_for_now(cfg)
    d = decide(state, cfg)
    try:
        apply_rules(cfg, d.tier)
    except RulesError as exc:
        save_state(cfg.state_path, rules_alert(cfg, state, str(exc)))
        raise
    state = apply_rate(
        cfg, dict(state, applied_rate=None, applied_tier=d.tier), d.rate_mbit
    )
    save_state(cfg.state_path, state)
    print(status_json(state, cfg))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick")
    sub.add_parser("apply")
    sub.add_parser("status")
    sub.add_parser("close")
    r = sub.add_parser("reopen")
    r.add_argument("--extra-gib", type=float, default=20)
    s = sub.add_parser("seed")
    s.add_argument("--gib", type=float, required=True)
    m = sub.add_parser("mail", help="send an operator email (used by deploy.sh)")
    m.add_argument("--subject", required=True)
    m.add_argument("--body", required=True)
    args = p.parse_args(argv)
    cfg = Config.load()
    if args.cmd == "mail":
        return 0 if send_email(cfg, args.subject, args.body) else 1
    if args.cmd == "tick":
        cmd_tick(cfg)
    elif args.cmd == "apply":
        cmd_apply(cfg)
    elif args.cmd == "status":
        print(status_json(_state_for_now(cfg), cfg))
    elif args.cmd in ("reopen", "seed", "close"):
        state = _state_for_now(cfg)
        if args.cmd == "reopen":
            state = reopen(state, int(args.extra_gib * GiB))
        elif args.cmd == "seed":
            state = seed(state, int(args.gib * GiB))
        else:
            state = dict(state, close_at=state["total"])
        save_state(cfg.state_path, state)
        cmd_apply(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
