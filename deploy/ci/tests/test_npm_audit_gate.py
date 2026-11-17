"""The npm audit gate: HIGH/CRITICAL advisories fail unless allowlisted and unexpired."""

import datetime as dt
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import npm_audit_gate as g  # noqa: E402

PICO = "GHSA-fc5q-39xc-vjpf"


def adv(gid, sev):
    return {"source": 1, "url": f"https://github.com/advisories/{gid}", "severity": sev}


def report(*extra):
    """picomatch's high advisory reached through vite (as npm reports it), plus extras."""
    vulns = {
        "picomatch": {"severity": "high", "via": [adv(PICO, "high")]},
        "vite": {"severity": "high", "via": ["picomatch", "fdir"]},
        "react-router": {"severity": "moderate", "via": [adv("GHSA-wrjc-x8rr-h8h6", "moderate")]},
    }
    for name, gid, sev in extra:
        vulns[name] = {"severity": sev, "via": [adv(gid, sev)]}
    return {"vulnerabilities": vulns}


def allowlist(tmp_path, expires="2026-12-17", **over):
    e = {"id": PICO, "expires": expires, "approved_by": "owner", "reason": "no fix yet"}
    e.update(over)
    p = tmp_path / "allow.json"
    p.write_text(json.dumps([e]))
    return p


def run(monkeypatch, rep, allow_path, today="2026-11-17"):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(rep)))
    return g.main(["--allowlist", str(allow_path), "--today", today])


def test_allowlisted_advisory_passes(monkeypatch, tmp_path, capsys):
    assert run(monkeypatch, report(), allowlist(tmp_path)) == 0
    assert "allowed GHSA-fc5q-39xc-vjpf" in capsys.readouterr().out


def test_without_allowlist_it_fails(monkeypatch, tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("[]")
    assert run(monkeypatch, report(), p) == 1


def test_expired_entry_fails_again(monkeypatch, tmp_path, capsys):
    assert run(monkeypatch, report(), allowlist(tmp_path, expires="2026-12-17"), today="2026-12-18") == 1
    assert "EXPIRED" in capsys.readouterr().out


def test_any_other_high_or_critical_fails(monkeypatch, tmp_path, capsys):
    for sev in ("high", "critical"):
        rep = report(("evil", "GHSA-aaaa-bbbb-cccc", sev))
        assert run(monkeypatch, rep, allowlist(tmp_path)) == 1
        assert "FAIL GHSA-aaaa-bbbb-cccc" in capsys.readouterr().out


def test_moderate_never_fails(monkeypatch, tmp_path):
    rep = report(("meh", "GHSA-mmmm-nnnn-oooo", "moderate"))
    assert run(monkeypatch, rep, allowlist(tmp_path)) == 0


def test_stale_entry_is_reported(monkeypatch, tmp_path, capsys):
    assert run(monkeypatch, {"vulnerabilities": {}}, allowlist(tmp_path)) == 0
    assert "no longer reported" in capsys.readouterr().out


def test_entry_without_approval_is_rejected(tmp_path):
    with pytest.raises(SystemExit):
        g.load_allowlist(allowlist(tmp_path, approved_by=""), dt.date(2026, 11, 17))


def test_committed_allowlist_is_valid():
    for e in json.loads(g.DEFAULT_ALLOWLIST.read_text()):
        assert e["approved_by"] and e["reason"]
        dt.date.fromisoformat(e["expires"])
