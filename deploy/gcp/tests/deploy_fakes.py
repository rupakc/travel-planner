#!/usr/bin/env python3
"""Fake docker / curl / systemctl / governor for test_deploy.py.

Installed into a temp bin directory under each command's name; reads and
writes the simulated world under $SIM:

  registry/app, registry/caddy   digest `prod` points at (sha256:...)
  registry/429                   present → manifests answer 429 (Retry-After)
  images/<hex>/labels            key=value image labels
  images/<hex>/srv/, Caddyfile   a Caddy image's content
  present                        refs pulled into the local image store
  running/app, running/caddy     ref each container runs
  running/caddy.hash             compose config hash Caddy was created with
  running/caddy.config           the config Caddy serves (adapted JSON)
  stopped                        services whose container exists but is stopped
  unhealthy                      app refs that never get healthy
  broken                         Caddy refs whose container never answers
  serve_500                      present → Caddy answers 500 over HTTPS
  verify_fail                    refs whose cosign verification fails
  reload_fail                    present → the admin API refuses /load
  streams                        open SSE streams (count; decays by 1 per poll)
  fail_pull, fail_create,        present → that docker command fails
  fail_cp, fail_adapt_infra      (adapt: docker's own exit 125)
  fail_up                        services whose `compose up` fails
  noop_up                        services whose `compose up` exits 0 but
                                 leaves the old container running
  calls.log                      one line per call, for assertions

Nothing here touches a real registry, container or unit.
"""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

SIM = Path(os.environ["SIM"])
EDGE = Path(os.environ["EDGE_DIR"])
COMPOSE_DIR = Path(os.environ["COMPOSE_DIR"])


def call(line: str) -> None:
    with open(SIM / "calls.log", "a") as f:
        f.write(line + "\n")


def lines(name: str) -> list[str]:
    p = SIM / name
    return p.read_text().split() if p.exists() else []


def add_line(name: str, value: str) -> None:
    with open(SIM / name, "a") as f:
        f.write(value + "\n")


def flag(name: str) -> bool:
    return (SIM / name).exists()


def hexof(ref: str) -> str:
    return ref.rsplit("@sha256:", 1)[-1]


def labels(ref: str) -> dict[str, str]:
    p = SIM / "images" / hexof(ref) / "labels"
    out = {}
    if p.exists():
        for ln in p.read_text().splitlines():
            k, _, v = ln.partition("=")
            out[k] = v
    return out


def images_env() -> dict[str, str]:
    out = {}
    p = COMPOSE_DIR / "images.env"
    if p.exists():
        for ln in p.read_text().splitlines():
            if "=" in ln and not ln.startswith("#"):
                k, _, v = ln.partition("=")
                out[k] = v
    return out


def caddy_hash() -> str:
    env = images_env()
    compose = (COMPOSE_DIR / "compose.yaml").read_text()
    return hashlib.sha256((env.get("CADDY_IMAGE", "") + compose).encode()).hexdigest()


def running(svc: str) -> str:
    p = SIM / "running" / svc
    return p.read_text() if p.exists() else ""


def up(svc: str) -> bool:
    """The service's container is running (exists and not stopped)."""
    return bool(running(svc)) and svc not in lines("stopped")


def caddy_ok() -> bool:
    return up("caddy") and running("caddy") not in lines("broken")


def edge_path(container_path: str) -> Path:
    assert container_path.startswith("/edge/"), container_path
    return EDGE / container_path.removeprefix("/edge/")


def unstop(svc: str) -> None:
    keep = [s for s in lines("stopped") if s != svc]
    (SIM / "stopped").write_text("".join(s + "\n" for s in keep))


# ── docker ───────────────────────────────────────────────────────────────


def compose(args: list[str]) -> int:
    call("compose " + " ".join(args[args.index("-f") + 2 :]))
    i = args.index("-f") + 2  # past `-f compose.yaml`
    sub = args[i:]
    if sub[:2] == ["ps", "-q"]:
        svc = sub[2]
        if running(svc):
            print(f"{svc}-cid")
        return 0
    if sub[:2] == ["config", "--hash"]:
        print(f"caddy {caddy_hash()}")
        return 0
    if sub[0] == "up":
        svcs = [a for a in sub[1:] if not a.startswith("-")] or ["app", "caddy"]
        if any(s in lines("fail_up") for s in svcs):
            print(
                "Error response from daemon: no space left on device", file=sys.stderr
            )
            return 1
        env = images_env()
        (SIM / "running").mkdir(exist_ok=True)
        for svc in svcs:
            if svc in lines("noop_up"):
                continue
            if svc == "app":
                ref = env["APP_IMAGE"]
                if running("app") != ref:
                    call(f"RECREATE app {ref}")
                elif "app" in lines("stopped"):
                    call("START app")
                (SIM / "running" / "app").write_text(ref)
                unstop("app")
            if svc == "caddy":
                ref, h = env["CADDY_IMAGE"], caddy_hash()
                hp = SIM / "running" / "caddy.hash"
                if running("caddy") != ref or not hp.exists() or hp.read_text() != h:
                    call(f"RECREATE caddy {ref}")
                    cf = EDGE / "current" / "Caddyfile"
                    (SIM / "running" / "caddy.config").write_text(
                        "caddyfile:" + (cf.read_text() if cf.exists() else "MISSING")
                    )
                elif "caddy" in lines("stopped"):
                    call("START caddy")
                (SIM / "running" / "caddy").write_text(ref)
                hp.write_text(h)
                unstop("caddy")
        return 0
    return 0


def docker(args: list[str]) -> int:
    call("docker " + " ".join(args))
    cmd = args[0]
    if cmd == "compose":
        return compose(args)
    if cmd == "ps":
        for svc in ("app", "caddy"):
            if running(svc):
                print(f"{svc} {'exited' if svc in lines('stopped') else 'running'}")
        return 0
    if cmd == "run":
        if "verify" in args and "--certificate-identity" in args:
            ref = args[-1]
            call(f"COSIGN {ref}")
            return 1 if ref in lines("verify_fail") else 0
        if "--entrypoint" in args and "adapt" in args:
            image = args[args.index("--entrypoint") + 2]
            if flag("fail_adapt_infra"):
                print(
                    "docker: Error response from daemon: OCI runtime", file=sys.stderr
                )
                return 125
            if image not in lines("present"):
                print(f"no such image {image}", file=sys.stderr)
                return 125
            cfg = edge_path(args[args.index("--config") + 1]).read_text()
            call(f"ADAPT {image}")
            if "INVALID" in cfg:
                print(
                    "Error: adapting config using caddyfile: INVALID", file=sys.stderr
                )
                return 1
            print(json.dumps({"adapted": cfg}))
            return 0
        return 0
    if cmd == "pull":
        ref = args[-1]
        if flag("fail_pull"):
            print("pull: TLS handshake timeout", file=sys.stderr)
            return 1
        if not (SIM / "images" / hexof(ref)).exists():
            return 1
        call(f"PULL {ref}")
        if ref not in lines("present"):
            add_line("present", ref)
        return 0
    if cmd == "image":
        sub, ref = args[1], args[-1]
        if sub == "inspect":
            if ref not in lines("present"):
                return 1
            if "-f" in args:
                fmt = args[args.index("-f") + 1]
                if fmt == "{{.Id}}":
                    print(f"id-{hexof(ref)}")
                else:
                    print(labels(ref).get(fmt.split('"')[1], "<no value>"))
            return 0
        if sub == "rm":
            if ref in (running("app"), running("caddy")):
                return 1
            call(f"RMI {ref}")
            keep = [r for r in lines("present") if r != ref]
            (SIM / "present").write_text("".join(r + "\n" for r in keep))
            return 0
        return 0
    if cmd == "create":
        ref = args[-1]
        if flag("fail_create") or ref not in lines("present"):
            return 1
        print(f"ctr-{hexof(ref)}")
        return 0
    if cmd == "cp":
        if flag("fail_cp"):
            return 1
        src, dest = args[1], args[2]
        cid, _, path = src.partition(":")
        img = SIM / "images" / cid.removeprefix("ctr-")
        what = img / ("srv" if path == "/srv" else "Caddyfile")
        if not what.exists():
            return 1
        if what.is_dir():
            shutil.copytree(what, dest, symlinks=True)
        else:
            shutil.copy(what, dest)
        return 0
    if cmd == "rm":
        return 0
    if cmd == "exec":
        cid = args[1]
        if cid != "caddy-cid" or not caddy_ok():
            return 1
        if args[2] == "test":
            return 0 if edge_path(args[-1]).is_file() else 1
        url = args[-1]
        if url.endswith("/load"):
            if flag("reload_fail"):
                call("RELOAD-REFUSED")
                return 1
            body = edge_path(args[args.index("--post-file") + 1]).read_text()
            call("RELOAD")
            (SIM / "running" / "caddy.config").write_text(
                "caddyfile:" + json.loads(body)["adapted"]
            )
            return 0
        return 0  # admin /config/
    if cmd == "inspect":
        fmt, cid = args[2], args[3]
        svc = cid.removesuffix("-cid")
        if "State.Health" in fmt:
            ref = running("app")
            if not up("app"):
                print("missing")
            else:
                print("unhealthy" if ref in lines("unhealthy") else "healthy")
            return 0
        if "State.Running" in fmt:
            print("true" if up(svc) else "false")
            return 0
        if fmt == "{{.Image}}":
            print(f"id-{hexof(running(svc))}")
            return 0
        if "config-hash" in fmt:
            p = SIM / "running" / "caddy.hash"
            print(p.read_text() if p.exists() else "")
            return 0
    return 0


# ── curl ─────────────────────────────────────────────────────────────────


def curl(args: list[str]) -> int:
    url = args[-1]
    opts: dict[str, str] = {}
    i = 0
    while i < len(args) - 1:
        a = args[i]
        if a in ("-D", "-o", "-w", "--resolve", "--max-time", "-H"):
            opts[a] = args[i + 1]
            i += 2
            continue
        i += 1
    code, headers, body = 200, "", ""
    if "/token?" in url:
        call("CURL token")
        body = '{"token":"t"}'
    elif "/manifests/" in url:
        repo = "caddy" if "-caddy/" in url else "app"
        call(f"CURL head {repo}")
        if (SIM / "registry" / "429").exists():
            code, headers = 429, "Retry-After: 120\r\n"
        else:
            digest = (SIM / "registry" / repo).read_text().strip()
            headers = f"Docker-Content-Digest: {digest}\r\n"
    elif "/internal/streams" in url:
        p = SIM / "streams"
        n = int(p.read_text()) if p.exists() else 0
        call(f"STREAMS {n}")
        if n > 0:
            p.write_text(str(n - 1))
        print(json.dumps({"active_streams": n}))
        return 0
    elif url.startswith("http://") and opts.get("-H", "").startswith("Host: "):
        # plain HTTP to Caddy: the site's redirect to HTTPS (no certificate needed)
        call("HTTP site")
        if not caddy_ok():
            if "-w" in opts:
                sys.stdout.write("000")
            return 7
        host = opts["-H"].removeprefix("Host: ")
        code, headers = 308, f"Location: https://{host}/\r\n"
    elif url.startswith("https://") and "--resolve" in opts:
        path = "/" + url.split("/", 3)[3] if url.count("/") >= 3 else "/"
        call(f"GET {path}")
        if not caddy_ok():
            if "-w" in opts:
                sys.stdout.write("000")
            return 7
        if flag("serve_500"):
            code = 500
        elif path == "/":
            body = (EDGE / "current" / "srv" / "index.html").read_text()
        else:
            code = 404
            for name in ("current", "prev1", "prev2"):
                f = EDGE / name / "srv" / path.lstrip("/")
                if f.is_file():
                    code, body = 200, f.read_text()
                    break
    else:
        call(f"CURL unexpected {url}")
        return 6
    if "-D" in opts:
        Path(opts["-D"]).write_text(f"HTTP/2 {code}\r\n{headers}\r\n")
    if "-o" in opts:
        if opts["-o"] != "/dev/null":
            Path(opts["-o"]).write_text(body)
    else:
        sys.stdout.write(body)
    if "-w" in opts:
        sys.stdout.write(str(code))
    return 0


# ── systemctl / governor (mail) ──────────────────────────────────────────


def systemctl(args: list[str]) -> int:
    add_line("systemctl.log", " ".join(args))
    if args[0] == "is-active":
        return 0 if (SIM / "unit_active").exists() else 3
    if args[0] == "start":
        if "--no-block" not in args:
            add_line("systemctl.log", "BLOCKING")
            return 99
        (SIM / "unit_active").touch()
    return 0


def governor(args: list[str]) -> int:
    subject = args[args.index("--subject") + 1]
    add_line("mail.log", subject.replace(" ", "_"))
    call(f"MAIL {subject}")
    return 0


def main() -> int:
    name = Path(sys.argv[0]).name
    handler = {
        "docker": docker,
        "curl": curl,
        "systemctl": systemctl,
        "governor.py": governor,
    }[name]
    return handler(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
