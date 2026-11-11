"""bootstrap.sh without GCP: gcloud and curl are stubs that record every
call. Covers the 2026-11-06 first-run follow-ups: the billing quota project,
the beta-component preflight, and a host bundle free of macOS metadata.
Run: python3 -m pytest infrastructure/gcp/tests -q"""

import base64
import os
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "infrastructure" / "gcp" / "bootstrap.sh"
ARGS = ["voyager-prod-ohzkl", "010A0B-F39593-14A899", "you@example.com"]

# Records "<name> <args> [quota=...]"; `gcloud components list` answers from
# $FAKE_COMPONENTS; everything else succeeds with no output
STUB = r"""#!/usr/bin/env bash
echo "$(basename "$0") $* [quota=${CLOUDSDK_BILLING_QUOTA_PROJECT:-}]" >>"$CALLS"
if [[ "$(basename "$0")" == gcloud && "$1 $2" == "components list" ]]; then
  printf '%s\n' $FAKE_COMPONENTS
fi
exit 0
"""


def run(tmp_path, *flags, components="core beta bq", env_extra=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("gcloud", "curl"):
        stub = bin_dir / name
        stub.write_text(STUB)
        stub.chmod(0o755)
    calls = tmp_path / "calls"
    calls.write_text("")
    base = {
        k: v for k, v in os.environ.items() if k != "CLOUDSDK_BILLING_QUOTA_PROJECT"
    }
    env = {
        **base,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "FAKE_COMPONENTS": components,
        "BOOTSTRAP_WORK": str(tmp_path / "work"),
        **(env_extra or {}),
    }
    p = subprocess.run(
        ["bash", str(SCRIPT), *flags, *ARGS],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return p, calls.read_text().splitlines()


def test_dry_run_calls_nothing(tmp_path):
    p, calls = run(tmp_path, "--dry-run")
    assert p.returncode == 0, p.stderr
    assert calls == []
    out = " ".join((p.stdout + p.stderr).split())
    assert "quota project: voyager-prod-ohzkl" in out
    # Alerting policies use the GA command group; only channels need beta
    assert "monitoring policies create" in out
    assert " alpha " not in out


def test_dry_run_update_host_calls_nothing(tmp_path):
    p, calls = run(tmp_path, "--dry-run", "--update-host")
    assert p.returncode == 0, p.stderr
    assert calls == []


def test_preflight_stops_before_any_change_without_beta(tmp_path):
    p, calls = run(tmp_path, components="core bq")
    assert p.returncode == 1
    assert "gcloud components install beta --quiet" in p.stderr
    # Only the local component listing ran: no project, API or billing call
    assert len(calls) == 1
    assert calls[0].startswith("gcloud components list --only-local-state")


def test_billing_calls_use_the_project_as_quota_project(tmp_path):
    # A whole run against the stubs: every call after the project lookup,
    # budgets (gcloud + the spend-cap curl) and monitoring included, carries
    # the project as its quota project
    p, calls = run(tmp_path)
    assert p.returncode == 0, p.stderr
    rest = [c for c in calls if "components list" not in c]
    assert "projects describe voyager-prod-ohzkl" in rest[0]
    later = rest[1:]
    assert any("billing budgets list" in c for c in later)
    assert any(c.startswith("curl ") for c in later)
    assert any("monitoring policies" in c for c in later)
    assert not any(" alpha " in c for c in calls)
    assert all(c.endswith("[quota=voyager-prod-ohzkl]") for c in later), later


def test_quota_project_set_by_caller_is_kept(tmp_path):
    p, calls = run(tmp_path, env_extra={"CLOUDSDK_BILLING_QUOTA_PROJECT": "other-proj"})
    assert p.returncode == 0, p.stderr
    later = [c for c in calls if "components list" not in c][1:]
    assert later and all(c.endswith("[quota=other-proj]") for c in later), later


def test_host_bundle_is_clean_and_ordered(tmp_path):
    p, _ = run(tmp_path, "--dry-run")
    assert p.returncode == 0, p.stderr
    raw = base64.b64decode((tmp_path / "work" / "bundle.b64").read_text())
    tgz = tmp_path / "bundle.tgz"
    tgz.write_bytes(raw)
    with tarfile.open(tgz) as tar:
        members = tar.getmembers()
    names = [m.name.removeprefix("./") for m in members]
    for m in members:
        # No LIBARCHIVE.xattr.* / SCHILY.xattr.* pax records (macOS
        # com.apple.provenance), no AppleDouble ._ files, root-owned
        assert not any("xattr" in k for k in m.pax_headers), (m.name, m.pax_headers)
        assert not Path(m.name).name.startswith("._"), m.name
        assert m.uid == 0 and m.gid == 0, m.name
    assert names == sorted(names)  # explicit, C-sorted file list
    expected = {
        "compose.yaml",
        "app.env.example",
        "host/first-boot.sh",
        "host/deploy.sh",
    }
    assert expected <= set(names)
    assert "host/systemd/voyager.service" in names
    assert not any(n.startswith("tests/") or "__pycache__" in n for n in names)


OAUTH_SECRETS = [
    "google-client-secret",
    "github-client-secret",
    "facebook-app-secret",
    "apple-private-key",
]


def test_dry_run_creates_oauth_secrets(tmp_path):
    p, _ = run(tmp_path, "--dry-run")
    assert p.returncode == 0, p.stderr
    out = " ".join((p.stdout + p.stderr).split())
    for s in OAUTH_SECRETS:
        assert f"secrets create {s} " in out, s


def test_app_env_example_names_only_bootstrapped_secrets():
    text = (ROOT / "deploy" / "gcp" / "app.env.example").read_text()
    line = next(x for x in text.splitlines() if x.startswith("SECRET_MANAGER_SECRETS="))
    ids = {
        v.strip().lower().replace("_", "-") for v in line.split("=", 1)[1].split(",")
    }
    script = SCRIPT.read_text()
    arr = script.split("SECRETS=(", 1)[1].split(")", 1)[0].split()
    assert ids == set(arr)
    assert set(OAUTH_SECRETS) <= ids


def test_app_env_example_names_are_settings_fields():
    import re
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    from app.core.config import Settings

    fields = {f.upper() for f in Settings.model_fields}
    text = (ROOT / "deploy" / "gcp" / "app.env.example").read_text()
    names = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, re.M))
    # Read by the container or the VM kit, not by Settings
    names -= {"SECRET_MANAGER_SECRETS", "FCM_PROJECT_ID"}
    assert names <= fields, sorted(names - fields)
