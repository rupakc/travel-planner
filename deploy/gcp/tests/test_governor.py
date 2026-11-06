"""Egress governor: pure counter, month and threshold logic (no root, no
network, no iptables). Run: python3 -m pytest deploy/gcp/tests -q"""

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "host" / "governor.py"
_spec = importlib.util.spec_from_file_location("governor", _PATH)
gov = importlib.util.module_from_spec(_spec)
sys.modules["governor"] = gov
_spec.loader.exec_module(gov)

GiB = 1024**3
CFG = gov.Config()


def ts(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC).timestamp()


# ── Month boundary: Google's billing month, US Pacific ──────────────────────


def test_month_key_follows_los_angeles_not_utc():
    # 2026-12-01 07:59 UTC is still 23:59 on Nov 30 in Los Angeles (PST, -8)
    assert gov.month_key(ts(2026, 12, 1, 7, 59)) == "2026-11"
    assert gov.month_key(ts(2026, 12, 1, 8, 0)) == "2026-12"


def test_month_key_handles_daylight_saving():
    # 2026-07-01 06:59 UTC = 23:59 PDT (-7) on Jun 30
    assert gov.month_key(ts(2026, 7, 1, 6, 59)) == "2026-06"
    assert gov.month_key(ts(2026, 7, 1, 7, 0)) == "2026-07"


# ── Counter deltas: reboot-safe ──────────────────────────────────────────────


def fresh(now=None):
    return gov.new_state(gov.month_key(now or ts(2026, 11, 10)), raw=0, boot_id="b1")


def test_first_tick_after_install_counts_nothing_before_it():
    s = gov.new_state("2026-11", raw=5 * GiB, boot_id="b1")
    s = gov.apply_tick(s, raw=5 * GiB + 100, boot_id="b1", now=ts(2026, 11, 10))
    assert s["total"] == 100


def test_normal_delta_accumulates():
    s = fresh()
    for raw in (1000, 5000, 9000):
        s = gov.apply_tick(s, raw=raw, boot_id="b1", now=ts(2026, 11, 10))
    assert s["total"] == 9000
    assert s["last_raw"] == 9000


def test_reboot_counter_reset_counts_the_new_value():
    s = fresh()
    s = gov.apply_tick(s, raw=10_000, boot_id="b1", now=ts(2026, 11, 10))
    # After a reboot the NIC counter restarts from 0; 300 bytes sent since
    s = gov.apply_tick(s, raw=300, boot_id="b2", now=ts(2026, 11, 10))
    assert s["total"] == 10_300
    assert s["boot_id"] == "b2"


def test_counter_going_backwards_on_same_boot_is_treated_as_a_reset():
    s = fresh()
    s = gov.apply_tick(s, raw=10_000, boot_id="b1", now=ts(2026, 11, 10))
    s = gov.apply_tick(s, raw=50, boot_id="b1", now=ts(2026, 11, 10))
    assert s["total"] == 10_050


def test_new_boot_with_a_higher_counter_still_counts_only_the_new_boot():
    s = fresh()
    s = gov.apply_tick(s, raw=100, boot_id="b1", now=ts(2026, 11, 10))
    s = gov.apply_tick(s, raw=5000, boot_id="b2", now=ts(2026, 11, 10))
    assert s["total"] == 5100


def test_month_rollover_resets_total_and_flags():
    s = fresh(ts(2026, 11, 30))
    s = gov.apply_tick(s, raw=199 * GiB, boot_id="b1", now=ts(2026, 11, 30))
    s.update(warned=True, closed=True, close_at=250 * GiB)
    s = gov.apply_tick(s, raw=199 * GiB + 500, boot_id="b1", now=ts(2026, 12, 1, 9))
    assert s["month"] == "2026-12"
    assert s["total"] == 500  # only bytes after the boundary tick
    assert (s["warned"], s["closed"], s["close_at"]) == (False, False, None)


# ── Thresholds ─────────────────────────────────────────────────────────────


def with_total(gib, **kw):
    s = fresh()
    s["total"] = int(gib * GiB)
    s.update(kw)
    return s


def test_below_warning_is_open_at_the_base_rate():
    d = gov.decide(with_total(10), CFG)
    assert d.tier == "open" and d.rate_mbit == 50
    assert not d.notify


def test_warning_at_150_gib_emails_once_and_slows_down():
    d = gov.decide(with_total(150), CFG)
    assert d.tier == "warn" and d.rate_mbit == 20
    assert d.notify == "warn"
    d2 = gov.decide(with_total(160, warned=True), CFG)
    assert d2.tier == "warn" and d2.notify is None


def test_close_at_200_gib():
    d = gov.decide(with_total(200, warned=True), CFG)
    assert d.tier == "closed" and d.notify == "close"
    assert gov.decide(with_total(201, warned=True, closed=True), CFG).notify is None


def test_close_also_warns_if_the_warning_was_skipped():
    d = gov.decide(with_total(205), CFG)
    assert d.tier == "closed" and d.notify == "close"


def test_reopen_raises_the_close_point_for_this_month_only():
    s = with_total(200, warned=True, closed=True)
    s = gov.reopen(s, extra_bytes=20 * GiB)
    assert s["close_at"] == 220 * GiB and s["closed"] is False
    assert gov.decide(s, CFG).tier == "warn"
    s["total"] = 220 * GiB
    assert gov.decide(s, CFG).tier == "closed"


def test_seed_never_lowers_the_total():
    s = with_total(40)
    assert gov.seed(s, 30 * GiB)["total"] == 40 * GiB
    assert gov.seed(s, 150 * GiB)["total"] == 150 * GiB


def test_single_ip_needs_over_60_days_to_reach_the_close():
    """§13.9: one IP at its 3 GiB/day quota cannot close the site in a month."""
    assert CFG.close_bytes / CFG.per_ip_daily_bytes > 60


# ── Persistence ────────────────────────────────────────────────────────────


def test_state_round_trips_atomically(tmp_path):
    path = tmp_path / "state.json"
    s = with_total(12.5)
    gov.save_state(path, s)
    assert gov.load_state(path) == s
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_corrupt_state_is_not_silently_reset(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    with pytest.raises(gov.StateError):
        gov.load_state(path)


def test_missing_state_returns_none(tmp_path):
    assert gov.load_state(tmp_path / "nope.json") is None


# ── Rules ──────────────────────────────────────────────────────────────────


def test_rules_live_in_docker_user_never_input():
    text = gov.render_restore(CFG, tier="open")
    assert text.startswith("*filter\n") and text.endswith("COMMIT\n")
    assert "-A DOCKER-USER -j VOYAGER-GUARD" in text
    assert "INPUT" not in text


def test_restore_declares_and_so_replaces_exactly_our_chains():
    text = gov.render_restore(CFG, tier="open")
    declared = [ln for ln in text.splitlines() if ln.startswith(":")]
    assert declared == [
        ":DOCKER-USER - [0:0]",
        ":VOYAGER-GUARD - [0:0]",
        ":VOYAGER-CLOSE - [0:0]",
        ":VOYAGER-EGRESS - [0:0]",
    ]


def test_every_rule_is_valid_iptables_shape():
    """iptables allows each of -s, -d, -i, -o once per rule (the bug that
    once broke VOYAGER-GUARD); real parsing runs in CI (iptables_harness)."""
    for tier in ("open", "warn", "closed"):
        for line in gov.rule_lines(CFG, tier):
            words = line.split()
            for opt in ("-s", "-d", "-i", "-o", "-j", "-p"):
                assert words.count(opt) <= 1, line


def test_open_tier_has_per_ip_rate_and_quota_but_no_close():
    flat = gov.render_restore(CFG, tier="open")
    assert "--hashlimit-mode dstip" in flat
    assert "--hashlimit-above 500kb/s" in flat  # ≈ 4 Mbit/s
    assert f"--bytes-gt {CFG.per_ip_daily_bytes}" in flat
    assert gov.close_rules(CFG, closed=False) == []


def test_closed_tier_drops_both_directions_of_web_traffic():
    rules = gov.close_rules(CFG, closed=True)
    assert any("--dports 80,443" in r and "DROP" in r for r in rules)
    assert any("--sports 80,443" in r and "DROP" in r for r in rules)


def test_tc_command_for_each_rate():
    assert gov.tc_command(CFG, 20) == [
        "tc", "qdisc", "replace", "dev", CFG.iface, "root", "tbf",
        "rate", "20mbit", "burst", "256kb", "latency", "400ms",
    ]  # fmt: skip


# ── Top talkers ───────────────────────────────────────────────────────────


IPSET_SAVE = """\
create voyager_perip hash:ip family inet hashsize 1024 maxelem 65536 timeout 86400 counters
add voyager_perip 203.0.113.9 timeout 80000 packets 10 bytes 900
add voyager_perip 198.51.100.7 timeout 70000 packets 99 bytes 5000000
add voyager_perip 192.0.2.1 timeout 60000 packets 3 bytes 120
"""


def test_top_talkers_parses_ipset_save_sorted_by_bytes():
    assert gov.top_talkers(IPSET_SAVE, n=2) == [
        ("198.51.100.7", 5_000_000),
        ("203.0.113.9", 900),
    ]


def test_status_line_is_json():
    line = gov.status_json(with_total(1), CFG)
    body = json.loads(line)
    assert body["month"] == "2026-11" and body["tier"] == "open"
    assert body["total_gib"] == 1.0


# ── tick, with the host faked ────────────────────────────────────────────────


class FakeHost:
    def __init__(self, monkeypatch, raw):
        self.raw = raw
        self.cmds: list[list[str]] = []
        self.emails: list[str] = []
        monkeypatch.setattr(gov, "read_raw", lambda cfg: self.raw)
        monkeypatch.setattr(gov, "read_boot_id", lambda: "boot")
        monkeypatch.setattr(gov, "run", self.run)
        monkeypatch.setattr(
            gov, "send_email", lambda cfg, subj, body: self.emails.append(subj)
        )

        self.restores: list[str] = []  # committed rulesets
        self.reject = False  # iptables-restore rejects the ruleset

    def run(self, cmd, check=True, input=None):
        import subprocess

        self.cmds.append(cmd)
        rc = 0
        if cmd[0] == "iptables-restore":
            if self.reject:
                rc = 2
            elif "--test" not in cmd:
                self.restores.append(input)
        elif "-C" in cmd:
            rc = 1  # checking a jump that isn't there fails, like iptables
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="bad rule")


def test_tick_closes_once_and_persists(monkeypatch, tmp_path, capsys):
    cfg = gov.Config(state_path=tmp_path / "s.json", warn_bytes=100, close_bytes=200)
    host = FakeHost(monkeypatch, raw=0)
    gov.cmd_tick(cfg)  # first tick: baseline only
    host.raw = 150
    gov.cmd_tick(cfg)
    host.raw = 260
    gov.cmd_tick(cfg)
    gov.cmd_tick(cfg)
    assert len(host.emails) == 2  # one warning, one close: never repeated
    assert "warning" in host.emails[0] and "CLOSED" in host.emails[1]
    state = gov.load_state(cfg.state_path)
    assert state["total"] == 260 and state["closed"] and state["warned"]
    assert any(
        "-A VOYAGER-CLOSE" in r and "--dports 80,443" in r for r in host.restores
    )
    tcs = [c for c in host.cmds if c[0] == "tc"]
    # 50 Mbit/s at start, 20 Mbit/s from the warning on; not re-applied each tick
    assert [c[c.index("rate") + 1] for c in tcs] == ["50mbit", "20mbit"]
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["tier"] == "closed"


# ── Review fixes ─────────────────────────────────────────────────────────────


def test_quota_check_does_not_count_bytes_a_second_time():
    rules = gov.rule_lines(CFG, tier="open")
    check = [r for r in rules if "--bytes-gt" in r]
    assert len(check) == 1 and "! --update-counters" in check[0]
    counting = [r for r in rules if "--match-set" in r and "--bytes-gt" not in r]
    assert len(counting) == 1  # exactly one rule updates the per-IP counters


def test_hashlimit_table_is_sized_explicitly():
    assert "--hashlimit-htable-max 65536" in gov.render_restore(CFG, tier="open")


def test_only_the_app_container_may_reach_the_metadata_server():
    meta = [r for r in gov.rule_lines(CFG, "open") if "169.254.169.254" in r]
    # The app's RETURN comes first; then everything else on the bridge drops
    assert meta == [
        f"-A VOYAGER-GUARD -s {CFG.app_ip}/32 -d 169.254.169.254/32 -j RETURN",
        f"-A VOYAGER-GUARD -i {CFG.bridge} -s {CFG.subnet} -d 169.254.169.254/32 -j DROP",
    ]
    assert any("VOYAGER-GUARD" in " ".join(s) for s in gov.jump_specs(CFG))


def test_unchanged_tier_does_not_rebuild_rules(monkeypatch, tmp_path):
    cfg = gov.Config(state_path=tmp_path / "s.json")
    host = FakeHost(monkeypatch, raw=0)
    # -C (check) succeeds: jumps are in place
    host_run = host.run

    def run(cmd, check=True, input=None):
        import subprocess

        if "-C" in cmd:
            host.cmds.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return host_run(cmd, check, input)

    monkeypatch.setattr(gov, "run", run)
    gov.cmd_tick(cfg)
    assert len(host.restores) == 1
    host.raw = 1000
    gov.cmd_tick(cfg)
    gov.cmd_tick(cfg)
    assert len(host.restores) == 1  # no rebuild (and no bucket reset) later


def test_missing_jumps_trigger_a_rebuild(monkeypatch, tmp_path):
    cfg = gov.Config(state_path=tmp_path / "s.json")
    host = FakeHost(monkeypatch, raw=0)  # its -C fails like -D: "missing"
    gov.cmd_tick(cfg)
    gov.cmd_tick(cfg)
    assert len(host.restores) == 2


def test_counted_bytes_are_saved_even_if_rules_fail(monkeypatch, tmp_path):
    cfg = gov.Config(state_path=tmp_path / "s.json")
    host = FakeHost(monkeypatch, raw=0)
    gov.cmd_tick(cfg)
    host.raw = 5000

    def docker_down(*a, **k):
        raise RuntimeError("DOCKER-USER chain missing")

    monkeypatch.setattr(gov, "apply_rules", docker_down)
    with pytest.raises(RuntimeError):
        gov.cmd_tick(cfg)
    assert gov.load_state(cfg.state_path)["total"] == 5000


def test_a_rejected_ruleset_keeps_the_old_rules_and_alerts_once(monkeypatch, tmp_path):
    cfg = gov.Config(state_path=tmp_path / "s.json", warn_bytes=100, close_bytes=200)
    host = FakeHost(monkeypatch, raw=0)
    gov.cmd_tick(cfg)  # open tier committed
    assert len(host.restores) == 1
    host.reject = True
    host.raw = 300  # past the close threshold: a new ruleset is needed
    with pytest.raises(gov.RulesError):
        gov.cmd_tick(cfg)
    # Validation failed, so nothing was committed: the old rules stay in force
    assert len(host.restores) == 1
    commits = [c for c in host.cmds if c[0] == "iptables-restore"]
    assert all("--test" in c for c in commits[-1:])
    state = gov.load_state(cfg.state_path)
    assert state["total"] == 300 and state["rules_error"]
    assert state["applied_tier"] == "open"  # not pretending it closed
    # tc and the threshold emails still happened
    assert any(c[0] == "tc" and "20mbit" in c for c in host.cmds)
    assert any("FAILED to apply" in e for e in host.emails)
    assert any("CLOSED" in e for e in host.emails)
    with pytest.raises(gov.RulesError):
        gov.cmd_tick(cfg)
    assert sum("FAILED to apply" in e for e in host.emails) == 1  # once
    host.reject = False
    gov.cmd_tick(cfg)
    assert len(host.restores) == 2 and "-A VOYAGER-CLOSE" in host.restores[-1]
    assert any("applied again" in e for e in host.emails)
    assert gov.load_state(cfg.state_path)["rules_error"] is None


# ── Boot-time unit wiring (no deadlock with the startup script) ─────────────

HOST = Path(__file__).resolve().parents[1] / "host"


def test_first_boot_never_blocks_on_a_unit_start():
    """first-boot.sh runs inside google-startup-scripts.service: a blocking
    `systemctl start/restart` of our units (which multi-user.target and
    docker.service also pull in) must never wait on a job queued behind it.
    (docker and zramswap are restarted blocking on purpose: nothing orders
    them after the startup script.)"""
    import re

    script = (HOST / "first-boot.sh").read_text()
    calls = [
        c
        for c in re.findall(r"systemctl (?:start|restart)\b[^\n]*", script)
        if "voyager" in c or "apt-daily" in c
    ]
    assert len(calls) >= 3
    assert all("--no-block" in c for c in calls), calls


def test_no_unit_waits_for_the_startup_script():
    for unit in (HOST / "systemd").glob("voyager*"):
        for line in unit.read_text().splitlines():
            if line.startswith(("After=", "Requires=", "Wants=", "BindsTo=")):
                assert "google-startup-scripts" not in line, (unit.name, line)


def test_voyager_service_comes_back_with_docker():
    unit = (HOST / "systemd" / "voyager.service").read_text()
    assert "WantedBy=multi-user.target docker.service" in unit
