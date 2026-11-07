"""build-decision.sh and promote-image.sh against fake docker/git/cosign
(fake_tools.py): when an image is built or skipped, and that `prod` moves
only after a HEAD check, a signature and a verification, for built images
only."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DECIDE = HERE.parent / "build-decision.sh"
PROMOTE = HERE.parent / "promote-image.sh"
IMG = "ghcr.io/o/app"
SHA = "a" * 40
OLD, NEW = "sha256:" + "1" * 64, "sha256:" + "2" * 64

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")


@pytest.fixture
def fake(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("docker", "git", "cosign"):
        shutil.copy(HERE / "fake_tools.py", bin_dir / name)
        (bin_dir / name).chmod(0o755)

    class Fake:
        dir = tmp_path

        def registry(self, tags=None, configs=None):
            (tmp_path / "registry.json").write_text(
                json.dumps({"tags": tags or {}, "configs": configs or {}})
            )

        def reg(self):
            return json.loads((tmp_path / "registry.json").read_text())

        def calls(self):
            p = tmp_path / "calls.log"
            return p.read_text().splitlines() if p.exists() else []

        def run(self, script, *args, **env):
            out = tmp_path / "out.txt"
            out.write_text("")
            summary = tmp_path / "summary.md"
            e = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_DIR": str(tmp_path),
                "GITHUB_OUTPUT": str(out),
                "GITHUB_STEP_SUMMARY": str(summary),
                **env,
            }
            r = subprocess.run(
                ["bash", str(script), *args],
                env=e,
                capture_output=True,
                text=True,
                check=False,
            )
            r.outputs = dict(
                line.split("=", 1)
                for line in out.read_text().splitlines()
                if "=" in line
            )
            return r

    f = Fake()
    f.registry(
        {f"{IMG}:prod": OLD},
        {
            f"{IMG}@{OLD}": {
                "io.voyager.app-inputs": "ID1",
                "io.voyager.fresh-at": str(FRESH),
            }
        },
    )
    return f


# ── build-decision.sh ─────────────────────────────────────────────────────
NOW = 2_000_000_000
FRESH = NOW - 3 * 86400  # refreshed 3 days ago
WEEK = 7 * 86400


def decide(fake, want, force="false", now=NOW):
    r = fake.run(DECIDE, "app", IMG, want, force, NOW=str(now))
    assert r.returncode == 0, r.stdout + r.stderr
    return r.outputs


def prod_labels(fake, labels):
    fake.registry({f"{IMG}:prod": OLD}, {f"{IMG}@{OLD}": labels})


def test_same_inputs_and_recent_refresh_skip(fake):
    assert decide(fake, "ID1") == {"build": "false", "prod": OLD}


def test_changed_inputs_build_with_cache_and_carry_the_refresh_time(fake):
    assert decide(fake, "ID2") == {
        "build": "true",
        "fresh": "false",
        "fresh_at": str(FRESH),
    }


def test_unknown_id_builds(fake):
    assert decide(fake, "")["build"] == "true"


def test_forced_run_refreshes(fake):
    assert decide(fake, "ID1", "true") == {
        "build": "true",
        "fresh": "true",
        "fresh_at": str(NOW),
    }


def test_a_push_refreshes_when_the_weekly_refresh_was_missed(fake):
    # e.g. the scheduled run was replaced by a queued push, or cron was disabled
    assert decide(fake, "ID1", now=FRESH + WEEK) == {"build": "false", "prod": OLD}
    assert decide(fake, "ID1", now=FRESH + WEEK + 1) == {
        "build": "true",
        "fresh": "true",
        "fresh_at": str(FRESH + WEEK + 1),
    }


@pytest.mark.parametrize(
    "setup",
    [
        lambda f: f.registry({}, {}),  # no prod tag
        lambda f: prod_labels(f, None),  # no labels at all
        lambda f: prod_labels(f, {"io.voyager.app-inputs": "ID1"}),  # no fresh-at
        lambda f: prod_labels(
            f, {"io.voyager.app-inputs": "ID1", "io.voyager.fresh-at": "soon"}
        ),
    ],
    ids=["no-prod", "no-labels", "no-fresh-at", "bad-fresh-at"],
)
def test_unreadable_prod_state_refreshes(fake, setup):
    setup(fake)
    assert decide(fake, "ID1") == {
        "build": "true",
        "fresh": "true",
        "fresh_at": str(NOW),
    }


def test_other_images_inputs_label_doesnt_count(fake):
    prod_labels(
        fake, {"io.voyager.caddy-inputs": "ID1", "io.voyager.fresh-at": str(FRESH)}
    )
    assert decide(fake, "ID1")["build"] == "true"


# ── promote-image.sh ──────────────────────────────────────────────────────
def promote(fake, **env):
    base = {
        "NAME": "app",
        "IMAGE": IMG,
        "REPO": "o/r",
        "SHA": SHA,
        "CERT_IDENTITY": "https://github.com/o/r/.github/workflows/deploy.yml@refs/heads/main",
        "CERT_ISSUER": "https://token.actions.githubusercontent.com",
        "FAKE_HEAD": SHA,
        "BUILT": "true",
        "NEW_DIGEST": NEW,
        "PROD_DIGEST": "",
    }
    return fake.run(PROMOTE, **{**base, **env})


def verbs(fake):
    return [
        " ".join(c.split()[:3])
        for c in fake.calls()
        if c.startswith(("cosign", "docker buildx imagetools create"))
    ]


def test_built_image_is_signed_verified_then_promoted(fake):
    r = promote(fake)
    assert r.returncode == 0, r.stdout + r.stderr
    assert verbs(fake) == [
        "cosign sign --yes",
        "cosign verify --certificate-identity",
        "docker buildx imagetools",
    ]
    sign = next(c for c in fake.calls() if c.startswith("cosign sign"))
    assert sign.endswith(f"{IMG}@{NEW}")
    assert fake.reg()["tags"][f"{IMG}:prod"] == NEW


def test_failed_verification_never_moves_prod(fake):
    r = promote(fake, FAKE_COSIGN_FAIL="verify")
    assert r.returncode != 0
    assert fake.reg()["tags"][f"{IMG}:prod"] == OLD


def test_failed_signing_never_moves_prod(fake):
    r = promote(fake, FAKE_COSIGN_FAIL="sign")
    assert r.returncode != 0
    assert not any(c.startswith("cosign verify") for c in fake.calls())
    assert fake.reg()["tags"][f"{IMG}:prod"] == OLD


def test_superseded_commit_is_neither_signed_nor_promoted(fake):
    r = promote(fake, FAKE_HEAD="b" * 40)
    assert r.returncode == 0
    assert "main moved on" in r.stdout
    assert verbs(fake) == []
    assert fake.reg()["tags"][f"{IMG}:prod"] == OLD


@pytest.mark.parametrize("head", ["", "not-a-sha", "A" * 40, "a" * 39])
def test_unreadable_head_fails(fake, head):
    r = promote(fake, FAKE_HEAD=head)
    assert r.returncode != 0
    assert verbs(fake) == []


def test_skipped_image_is_not_signed_and_prod_is_checked(fake):
    r = promote(fake, BUILT="false", NEW_DIGEST="", PROD_DIGEST=OLD)
    assert r.returncode == 0, r.stdout
    assert verbs(fake) == []
    assert "unchanged" in (fake.dir / "summary.md").read_text()


def test_skipped_image_fails_when_prod_moved_meanwhile(fake):
    r = promote(fake, BUILT="false", NEW_DIGEST="", PROD_DIGEST=NEW)
    assert r.returncode != 0
    assert "moved to" in r.stdout


@pytest.mark.parametrize(
    "env",
    [
        {"BUILT": ""},
        {"BUILT": "maybe"},
        {"NEW_DIGEST": ""},
        {"NEW_DIGEST": "sha256:xyz"},
        {"BUILT": "false", "PROD_DIGEST": ""},
    ],
    ids=["no-decision", "bad-decision", "no-digest", "bad-digest", "skip-without-prod"],
)
def test_missing_inputs_fail_closed(fake, env):
    r = promote(fake, **env)
    assert r.returncode != 0
    assert verbs(fake) == []
    assert fake.reg()["tags"][f"{IMG}:prod"] == OLD


def test_tag_not_landing_on_the_digest_fails(fake):
    r = promote(fake, FAKE_RETAG="wrong")
    assert r.returncode != 0
    assert "expected" in r.stdout
