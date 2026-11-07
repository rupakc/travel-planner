"""deploy.sh end to end with fake docker/curl/systemctl (deploy_fakes.py): no
registry, no containers, no root. Linux only (flock, GNU coreutils), like the
VM; CI runs it in the backend test job and in host_checks.sh (Debian 13).

Covers the app (upgrade, health rollback, holds, downgrades, --rollback) and
the edge: SPA swap without a restart, Caddyfile hot reload, Caddy runtime
changes (drain + recreate + checks + rollback), migration from the old
images.env with the image-baked SPA, pruning, GHCR back-off, signature
failures and the cheap no-change run.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DEPLOY = HERE.parent / "host" / "deploy.sh"
FAKES = HERE / "deploy_fakes.py"
APP = "ghcr.io/rupakc/travel-planner-app"
CADDY = "ghcr.io/rupakc/travel-planner-caddy"

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("flock") is None,
    reason="deploy.sh needs Linux (flock, GNU mv -T/stat -c), like the VM",
)

CADDYFILE = "{$SITE_HOST} {\n\tfile_server\n}\n"


def d(n: int) -> str:
    return f"sha256:{n:064d}"


class World:
    """The simulated VM + registry around one deploy.sh."""

    def __init__(self, root: Path):
        self.sim = root / "sim"
        self.opt = root / "opt"
        self.edge = root / "edge"
        self.state = root / "run"
        for p in (
            self.sim / "bin",
            self.sim / "images",
            self.sim / "registry",
            self.opt,
        ):
            p.mkdir(parents=True)
        (self.opt / "site.env").write_text("SITE_HOST=x.sslip.io\nACME_EMAIL=a@b.c\n")
        (self.opt / "compose.yaml").write_text("services: {} # v1\n")
        for name in ("docker", "curl", "systemctl"):
            dst = self.sim / "bin" / name
            shutil.copy(FAKES, dst)
            dst.chmod(0o755)
        shutil.copy(FAKES, self.opt / "governor.py")
        (self.opt / "governor.py").chmod(0o755)
        logger = self.sim / "bin" / "logger"
        logger.write_text("#!/bin/sh\nexit 0\n")
        logger.chmod(0o755)
        self.env = {
            **os.environ,
            "SIM": str(self.sim),
            "PATH": f"{self.sim / 'bin'}:{os.environ['PATH']}",
            "COMPOSE_DIR": str(self.opt),
            "EDGE_DIR": str(self.edge),
            "STATE_DIR": str(self.state),
            "LOCK": str(root / "lock"),
            "VOYAGER_DEPLOY_CONFIG": str(root / "none"),
            "HEALTH_TIMEOUT": "0",
            "CADDY_HEALTH_TIMEOUT": "0",
            "DRAIN_TIMEOUT": "30",
            "POLL": "0",
            "APP_STREAMS_URL": "http://172.30.0.10:8001/internal/streams",
        }
        self.output = ""

    # ── registry / images ──
    def app_image(self, n: int, build: int) -> str:
        img = self.sim / "images" / d(n).removeprefix("sha256:")
        img.mkdir()
        (img / "labels").write_text(f"io.voyager.build={build}\n")
        return f"{APP}@{d(n)}"

    def caddy_image(
        self,
        n: int,
        build: int,
        runtime: str | None = "r1",
        spa: str | None = None,
        caddyfile: str = CADDYFILE,
        extra: dict[str, str] | None = None,
    ) -> str:
        img = self.sim / "images" / d(n).removeprefix("sha256:")
        srv = img / "srv"
        (srv / "assets").mkdir(parents=True)
        tag = spa or f"v{n}"
        (srv / "index.html").write_text(
            f'<html><script type="module" src="/assets/index-{tag}.js"></script>'
            f'<link rel="stylesheet" href="/assets/index-{tag}.css"></html>\n'
        )
        (srv / "assets" / f"index-{tag}.js").write_text(f"js {tag}\n")
        (srv / "assets" / f"index-{tag}.css").write_text(f"css {tag}\n")
        (srv / "favicon.svg").write_text("<svg/>\n")
        for rel, content in (extra or {}).items():
            (srv / rel).write_text(content)
        (img / "Caddyfile").write_text(caddyfile)
        lbl = f"io.voyager.build={build}\n"
        if runtime:
            lbl += f"io.voyager.caddy-runtime={runtime}\n"
        (img / "labels").write_text(lbl)
        return f"{CADDY}@{d(n)}"

    def prod(self, app: str | None = None, caddy: str | None = None) -> None:
        if app:
            (self.sim / "registry" / "app").write_text(app.split("@")[1])
        if caddy:
            (self.sim / "registry" / "caddy").write_text(caddy.split("@")[1])

    def flag(self, name: str, value: str = "") -> None:
        with open(self.sim / name, "a") as f:
            f.write(value + "\n" if value else "")

    def unflag(self, name: str) -> None:
        (self.sim / name).unlink(missing_ok=True)

    # ── run + inspect ──
    def run(self, *args: str) -> int:
        (self.sim / "calls.log").write_text("")
        p = subprocess.run(
            ["bash", str(DEPLOY), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.output = p.stderr
        return p.returncode

    @property
    def calls(self) -> list[str]:
        return (self.sim / "calls.log").read_text().splitlines()

    def count(self, prefix: str) -> int:
        return sum(1 for c in self.calls if c.startswith(prefix))

    def images(self) -> dict[str, str]:
        out = {}
        for ln in (self.opt / "images.env").read_text().splitlines():
            if "=" in ln and not ln.startswith("#"):
                k, _, v = ln.partition("=")
                out[k] = v
        return out

    def link(self, name: str) -> str:
        p = self.edge / name
        return os.readlink(p) if p.is_symlink() else ""

    def release_of(self, ref: str) -> str:
        return "releases/" + ref.split("@sha256:")[1]

    def served_index(self) -> str:
        return (self.edge / "current" / "srv" / "index.html").read_text()

    def caddy_config(self) -> str:
        return (self.sim / "running" / "caddy.config").read_text()

    def held(self) -> list[str]:
        p = self.opt / "failed-digests"
        return p.read_text().split() if p.exists() else []

    def mails(self) -> list[str]:
        p = self.sim / "mail.log"
        return p.read_text().split() if p.exists() else []

    def starts(self) -> int:
        p = self.sim / "systemctl.log"
        log = p.read_text().splitlines() if p.exists() else []
        assert "BLOCKING" not in log
        return log.count("start --no-block voyager.service")


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


@pytest.fixture
def live(w):
    """A VM after its first deploy: app 1 (build 1) + Caddy 100 (build 1)."""
    w.prod(w.app_image(1, 1), w.caddy_image(100, 1))
    assert w.run() == 0, w.output
    return w


# ── First deploy ────────────────────────────────────────────────────────


def test_first_deploy_on_a_fresh_vm(w):
    app, caddy = w.app_image(1, 1), w.caddy_image(100, 1)
    w.prod(app, caddy)
    assert w.run() == 0, w.output
    img = w.images()
    assert img["APP_IMAGE"] == app
    assert img["CADDY_IMAGE"] == caddy
    assert img["CADDY_CONTENT_IMAGE"] == caddy
    assert "PENDING_CADDY_IMAGE" not in img
    assert w.link("current") == w.release_of(caddy)
    assert "index-v100.js" in w.served_index()
    assert w.count("COSIGN") == 2
    # voyager.service queued (--no-block) so its ExecStop runs at shutdown
    assert w.starts() == 1


def test_release_files_are_plain_world_readable_and_described(live):
    rel = live.edge / live.release_of(f"{CADDY}@{d(100)}")
    assert (rel / "SOURCE").read_text().strip() == f"{CADDY}@{d(100)}"
    assert (rel / "BUILD").read_text().strip() == "1"
    for p in [rel, *rel.rglob("*")]:
        assert not p.is_symlink()
        mode = p.stat().st_mode & 0o7777
        assert mode == (0o755 if p.is_dir() else 0o644), (p, oct(mode))
    # relative links: valid inside the container's /edge mount too
    assert not os.path.isabs(live.link("current"))


def test_nothing_new_is_cheap(live):
    assert live.run() == 0, live.output
    assert live.count("COSIGN") == 0
    assert live.count("PULL") == 0
    assert live.count("RECREATE") == 0
    assert live.count("CURL head") == 2
    # the anonymous token is cached: two HEAD requests and nothing else
    assert live.count("CURL token") == 0
    assert not any(c.startswith(("docker run", "docker create")) for c in live.calls)


# ── App ─────────────────────────────────────────────────────────────────


def test_app_upgrade_rollback_hold_and_downgrade(live):
    w = live
    w.prod(app=w.app_image(2, 2))
    assert w.run() == 0
    assert w.images()["APP_IMAGE"] == f"{APP}@{d(2)}"
    assert w.count("RECREATE app") == 1 and w.count("RECREATE caddy") == 0

    assert w.run("--rollback") == 0
    assert w.images()["APP_IMAGE"] == f"{APP}@{d(1)}"
    assert f"{APP}@{d(2)}" in w.held()
    assert w.run() == 0
    assert w.images()["APP_IMAGE"] == f"{APP}@{d(1)}", "held digest redeployed"
    assert w.count("COSIGN") == 0

    w.prod(app=w.app_image(3, 3))  # a newer digest ends the hold
    assert w.run() == 0
    assert w.images()["APP_IMAGE"] == f"{APP}@{d(3)}"

    bad = w.app_image(4, 4)
    w.flag("unhealthy", bad)
    w.prod(app=bad)
    assert w.run() == 1
    assert w.images()["APP_IMAGE"] == f"{APP}@{d(3)}"
    assert bad in w.held()
    assert "[voyager]_deploy_rolled_back" in w.mails()
    assert w.run() == 0 and w.count("COSIGN") == 0  # held: not retried

    w.prod(app=f"{APP}@{d(1)}")  # prod moved back to an older build
    assert w.run() == 0
    assert w.images()["APP_IMAGE"] == f"{APP}@{d(3)}"
    assert w.run() == 0 and w.count("COSIGN") == 0  # refusal remembered
    assert w.run("--allow-downgrade") == 0
    assert w.images()["APP_IMAGE"] == f"{APP}@{d(1)}"


def test_stopped_unit_is_started_again(live):
    (live.sim / "unit_active").unlink()
    assert live.run() == 0
    assert live.starts() == 2


# ── Edge: SPA swap, Caddyfile reload ─────────────────────────────────────


def test_content_only_update_swaps_the_spa_without_restart(live):
    w = live
    new = w.caddy_image(101, 2)
    w.prod(caddy=new)
    assert w.run() == 0, w.output
    assert w.count("RECREATE") == 0
    assert w.count("RELOAD") == 0 and w.count("ADAPT") == 0  # Caddyfile unchanged
    img = w.images()
    assert img["CADDY_IMAGE"] == f"{CADDY}@{d(100)}"  # runtime untouched
    assert img["CADDY_CONTENT_IMAGE"] == new
    assert img["PREV_CADDY_CONTENT_IMAGE"] == f"{CADDY}@{d(100)}"
    assert w.link("current") == w.release_of(new)
    assert w.link("prev1") == w.release_of(f"{CADDY}@{d(100)}")
    assert "index-v101.js" in w.served_index()
    assert w.count("GET /") >= 2  # index + an asset checked through Caddy
    assert f"RMI {new}" in w.calls  # content image dropped once extracted
    assert w.run() == 0 and w.count("COSIGN") == 0


def test_changed_caddyfile_is_validated_and_hot_reloaded(live):
    w = live
    new = w.caddy_image(101, 2, caddyfile=CADDYFILE + "# header tweak\n")
    w.prod(caddy=new)
    assert w.run() == 0, w.output
    assert w.count("RECREATE") == 0
    # validated with the running runtime image, never inside Caddy's container
    assert f"ADAPT {CADDY}@{d(100)}" in w.calls
    assert w.count("RELOAD") == 1
    assert "# header tweak" in w.caddy_config()
    rel = w.edge / w.release_of(new)
    assert (rel / "caddy.json").exists()


def test_invalid_caddyfile_is_refused_before_anything_switches(live):
    w = live
    new = w.caddy_image(101, 2, caddyfile="INVALID {\n")
    w.prod(caddy=new)
    assert w.run() == 1
    assert w.link("current") == w.release_of(f"{CADDY}@{d(100)}")
    assert w.count("RELOAD") == 0
    assert new in w.held()
    assert "[voyager]_Caddy_deploy_refused" in w.mails()
    assert not (w.edge / w.release_of(new)).exists()  # pruned


def test_reload_failure_keeps_old_config_and_switches_back(live):
    w = live
    before = w.caddy_config()
    new = w.caddy_image(101, 2, caddyfile=CADDYFILE + "# new\n")
    w.prod(caddy=new)
    w.flag("reload_fail")
    assert w.run() == 1
    assert w.link("current") == w.release_of(f"{CADDY}@{d(100)}")
    assert w.link("prev1") == ""
    assert w.caddy_config() == before
    assert w.images()["CADDY_CONTENT_IMAGE"] == f"{CADDY}@{d(100)}"
    assert new in w.held()
    assert "[voyager]_Caddy_deploy_refused" in w.mails()
    w.unflag("reload_fail")
    assert w.run() == 0 and w.count("COSIGN") == 0  # held


def test_spa_not_served_after_switch_rolls_back(live):
    w = live
    w.flag("serve_500")
    new = w.caddy_image(101, 2)
    w.prod(caddy=new)
    assert w.run() == 1
    assert w.link("current") == w.release_of(f"{CADDY}@{d(100)}")
    assert new in w.held()


def test_symlink_in_the_spa_is_refused(live):
    w = live
    new = w.caddy_image(101, 2)
    os.symlink("/etc/passwd", w.sim / "images" / d(101)[7:] / "srv" / "assets" / "x.js")
    w.prod(caddy=new)
    assert w.run() == 1
    assert "non-regular file" in w.output
    assert w.link("current") == w.release_of(f"{CADDY}@{d(100)}")
    assert new in w.held()
    assert not any(p.is_symlink() for p in (w.edge / "releases").rglob("*"))


def test_index_loading_a_missing_asset_is_refused(live):
    w = live
    new = w.caddy_image(101, 2)
    (w.sim / "images" / d(101)[7:] / "srv" / "assets" / "index-v101.js").unlink()
    w.prod(caddy=new)
    assert w.run() == 1
    assert "missing /assets/index-v101.js" in w.output
    assert w.link("current") == w.release_of(f"{CADDY}@{d(100)}")


def test_prune_keeps_three_releases_and_older_assets_stay_servable(live):
    w = live
    for n in (101, 102, 103):
        w.prod(caddy=w.caddy_image(n, n - 99))
        assert w.run() == 0, w.output
    releases = sorted(p.name for p in (w.edge / "releases").iterdir())
    assert len(releases) == 3
    assert w.link("current") == w.release_of(f"{CADDY}@{d(103)}")
    assert w.link("prev1") == w.release_of(f"{CADDY}@{d(102)}")
    assert w.link("prev2") == w.release_of(f"{CADDY}@{d(101)}")
    # a browser holding release 101's or 102's index.html still gets its chunks
    for tag in ("v101", "v102", "v103"):
        found = [
            n
            for n in ("current", "prev1", "prev2")
            if (w.edge / n / "srv" / "assets" / f"index-{tag}.js").is_file()
        ]
        assert found, tag
    assert not (w.edge / w.release_of(f"{CADDY}@{d(100)}")).exists()


# ── Edge: Caddy runtime ──────────────────────────────────────────────────


def test_runtime_change_drains_recreates_and_checks(live):
    w = live
    new = w.caddy_image(101, 2, runtime="r2")
    w.prod(caddy=new)
    (w.sim / "streams").write_text("3")
    assert w.run() == 0, w.output
    calls = w.calls
    recreate = calls.index(f"RECREATE caddy {new}")
    drained = [i for i, c in enumerate(calls) if c == "STREAMS 0"]
    assert drained and drained[0] < recreate, "recreated before the streams ended"
    assert w.count("STREAMS") == 4
    assert f"ADAPT {new}" in calls  # validated with the NEW image's Caddy
    img = w.images()
    assert img["CADDY_IMAGE"] == new
    assert img["PREV_CADDY_IMAGE"] == f"{CADDY}@{d(100)}"
    assert img["CADDY_CONTENT_IMAGE"] == new
    assert w.count("RECREATE caddy") == 1
    assert any(c == "GET /" for c in calls[recreate:])  # served after recreate


def test_drain_gives_up_after_the_timeout(live):
    w = live
    w.env["DRAIN_TIMEOUT"] = "0"
    w.prod(caddy=w.caddy_image(101, 2, runtime="r2"))
    (w.sim / "streams").write_text("50")
    assert w.run() == 0
    assert "still open" in w.output
    assert w.count("RECREATE caddy") == 1


def test_runtime_recreate_failure_rolls_back(live):
    w = live
    new = w.caddy_image(101, 2, runtime="r2")
    w.flag("broken", new)
    w.prod(caddy=new)
    assert w.run() == 1
    img = w.images()
    assert img["CADDY_IMAGE"] == f"{CADDY}@{d(100)}"
    assert img["CADDY_CONTENT_IMAGE"] == f"{CADDY}@{d(100)}"
    assert w.link("current") == w.release_of(f"{CADDY}@{d(100)}")
    assert new in w.held()
    assert w.count("RECREATE caddy") == 2  # new, then back
    assert "[voyager]_Caddy_deploy_rolled_back" in w.mails()
    assert w.run() == 0 and w.count("RECREATE") == 0 and w.count("COSIGN") == 0


def test_caddy_downgrade_refused_and_remembered(live):
    w = live
    w.prod(caddy=w.caddy_image(102, 5))
    assert w.run() == 0
    old = w.caddy_image(101, 3)
    w.prod(caddy=old)
    assert w.run() == 0
    assert w.images()["CADDY_CONTENT_IMAGE"] == f"{CADDY}@{d(102)}"
    assert "built before the live release" in w.output
    assert w.run() == 0 and w.count("COSIGN") == 0
    assert w.run("--allow-downgrade") == 0
    assert w.images()["CADDY_CONTENT_IMAGE"] == old


def test_signature_failure_is_refused_and_not_retried_every_minute(live):
    w = live
    new = w.caddy_image(101, 2)
    w.flag("verify_fail", new)
    w.prod(caddy=new)
    assert w.run() == 1
    assert w.count("PULL") == 0
    assert w.images()["CADDY_CONTENT_IMAGE"] == f"{CADDY}@{d(100)}"
    assert "signature check FAILED" in w.output
    assert w.run() == 1
    assert w.count("COSIGN") == 0  # retried after 10 min, not every minute


# ── Converge ─────────────────────────────────────────────────────────────


def test_compose_change_for_caddy_drains_before_recreate(live):
    w = live
    (w.opt / "compose.yaml").write_text("services: {} # v2\n")
    (w.sim / "streams").write_text("1")
    assert w.run() == 0
    calls = w.calls
    assert calls.index("STREAMS 0") < calls.index(f"RECREATE caddy {CADDY}@{d(100)}")
    assert w.run() == 0 and w.count("RECREATE") == 0


def test_rate_limited_registry_backs_off(live):
    w = live
    (w.state / "token").unlink()
    w.flag("registry/429")
    assert w.run() == 1
    assert "backing off" in w.output
    assert (w.state / "backoff").exists()
    w.unflag("registry/429")
    assert w.run() == 0
    assert w.count("CURL") == 0  # still backing off: GHCR not asked
    (w.state / "backoff").write_text("0 1")  # back-off over
    assert w.run() == 0
    assert w.count("CURL head") == 2
    assert not (w.state / "backoff").exists()


# ── Rollbacks ────────────────────────────────────────────────────────────


def test_rollback_edge_swaps_back_and_holds(live):
    w = live
    new = w.caddy_image(101, 2, caddyfile=CADDYFILE + "# v2\n")
    w.prod(caddy=new)
    assert w.run() == 0
    assert w.run("--rollback-edge") == 0, w.output
    assert w.link("current") == w.release_of(f"{CADDY}@{d(100)}")
    # the release we left stays an asset fallback for browsers that loaded it
    assert w.link("prev1") == w.release_of(new)
    assert w.images()["CADDY_CONTENT_IMAGE"] == f"{CADDY}@{d(100)}"
    assert w.count("RELOAD") == 1 and "# v2" not in w.caddy_config()
    assert w.count("RECREATE") == 0
    assert new in w.held()
    assert w.run() == 0
    assert w.link("current") == w.release_of(f"{CADDY}@{d(100)}")


def test_rollback_caddy_runtime(live):
    w = live
    new = w.caddy_image(101, 2, runtime="r2")
    w.prod(caddy=new)
    assert w.run() == 0
    assert w.run("--rollback-caddy") == 0, w.output
    img = w.images()
    assert img["CADDY_IMAGE"] == f"{CADDY}@{d(100)}"
    assert img["PREV_CADDY_IMAGE"] == new
    assert new in w.held()
    assert w.count("RECREATE caddy") == 1


def test_window_flag_is_a_harmless_alias(live):
    w = live
    new = w.caddy_image(101, 2)
    w.prod(caddy=new)
    assert w.run("--window") == 0
    assert w.images()["CADDY_CONTENT_IMAGE"] == new
    assert w.count("RECREATE") == 0


# ── Migration from the image-baked SPA (old images.env) ──────────────────


def _old_vm(w: World, pending: str = "") -> str:
    """The VM before this change: Caddy runs an unlabelled image with its SPA
    baked in, no edge directory, images.env without the content keys."""
    old_caddy = w.caddy_image(90, 1, runtime=None, spa="old")
    app = w.app_image(1, 1)
    w.flag("present", old_caddy)
    w.flag("present", app)
    (w.opt / "images.env").write_text(
        f"APP_IMAGE={app}\nCADDY_IMAGE={old_caddy}\nPREV_APP_IMAGE=\n"
        f"PREV_CADDY_IMAGE=\nPENDING_CADDY_IMAGE={pending}\nUPDATED=x\n"
    )
    run = w.sim / "running"
    run.mkdir()
    (run / "app").write_text(app)
    (run / "caddy").write_text(old_caddy)
    (run / "caddy.hash").write_text("hash-of-the-old-compose.yaml")
    (run / "caddy.config").write_text("baked")
    (w.sim / "unit_active").touch()
    (w.opt / "compose.yaml").write_text("services: {} # new, with the edge mount\n")
    w.prod(app, old_caddy)
    return old_caddy


def test_migration_with_the_new_image_published_recreates_caddy_once(w):
    _old_vm(w)
    new = w.caddy_image(101, 2, runtime="r1")
    w.prod(caddy=new)
    (w.sim / "streams").write_text("2")
    assert w.run() == 0, w.output
    assert w.count("RECREATE caddy") == 1
    assert f"RECREATE caddy {new}" in w.calls
    img = w.images()
    assert img["CADDY_IMAGE"] == new and img["CADDY_CONTENT_IMAGE"] == new
    assert "PENDING_CADDY_IMAGE" not in img
    assert w.link("current") == w.release_of(new)
    assert "index-v101.js" in w.served_index()
    # the old image's SPA stays as an asset fallback
    assert (w.edge / "prev1" / "srv" / "assets" / "index-old.js").is_file()
    assert w.run() == 0 and w.count("RECREATE") == 0


def test_migration_before_the_new_image_keeps_serving_the_old_spa(w):
    old = _old_vm(w)
    assert w.run() == 0, w.output
    assert w.link("current") == w.release_of(old)
    assert "index-old.js" in w.served_index()
    assert w.images()["CADDY_CONTENT_IMAGE"] == old
    assert w.count("RECREATE caddy") == 1  # the new compose.yaml, drained
    assert w.run() == 0 and w.count("RECREATE") == 0


def test_lost_edge_directory_is_rebuilt_from_the_pinned_image(live):
    w = live
    shutil.rmtree(w.edge)
    assert w.run() == 0, w.output
    assert w.link("current") == w.release_of(f"{CADDY}@{d(100)}")
    assert w.count("RECREATE") == 0
