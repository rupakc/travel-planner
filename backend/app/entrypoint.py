"""Container entrypoint: ``python -m app.entrypoint``.

1. When ``SECRET_MANAGER_SECRETS`` is set (production), fetch each named
   secret's latest version from Secret Manager with the VM's identity
   (Application Default Credentials) straight into this process's
   environment. Nothing is written to disk, so PD snapshots never hold a
   secret. Spec: comma-separated ``ENV_VAR`` (secret id = lower-case,
   dashes: ``JWT_SECRET_KEY`` → ``jwt-secret-key``) or ``ENV_VAR=secret-id``.
   A secret with no version yet is skipped; an env var that is already set
   wins.
2. Refuse to start without ``JWT_SECRET_KEY``.
3. ``exec`` uvicorn (one worker, ``--timeout-graceful-shutdown 5``).
   ``FORWARDED_ALLOW_IPS`` must list explicit addresses or networks (the
   compose network that Caddy lives on); ``*`` is refused, since it would
   let any client spoof ``X-Forwarded-For`` and so its rate-limit key.
"""

from __future__ import annotations

import base64
import ipaddress
import logging
import os
import re
import sys
from collections.abc import Callable

import httpx

logger = logging.getLogger("app.entrypoint")

SPEC_ENV = "SECRET_MANAGER_SECRETS"
CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"
ACCESS_URL = (
    "https://secretmanager.googleapis.com/v1/projects/{project}/secrets/"
    "{secret}/versions/latest:access"
)
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


class StartupError(RuntimeError):
    pass


def parse_spec(spec: str) -> list[tuple[str, str]]:
    out = []
    for raw in spec.split(","):
        item = raw.strip()
        if not item:
            continue
        var, sep, sid = item.partition("=")
        var, sid = var.strip(), sid.strip()
        if not sep:
            sid = var.lower().replace("_", "-")
        if not _ENV_RE.match(var) or not _SECRET_RE.match(sid) or "=" in sid:
            raise StartupError(f"bad {SPEC_ENV} entry: {item!r}")
        out.append((var, sid))
    return out


class SecretManagerAccessor:
    """``accessor(project, secret_id) -> str | None`` over the REST API."""

    def __init__(
        self,
        token: Callable[[], str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self._token = token or _adc_token
        self._transport = transport

    def __call__(self, project: str, secret_id: str) -> str | None:
        url = ACCESS_URL.format(project=project, secret=secret_id)
        with httpx.Client(transport=self._transport, timeout=15) as client:
            r = client.get(url, headers={"Authorization": f"Bearer {self._token()}"})
        if r.status_code == 200:
            data = r.json()["payload"]["data"]
            return base64.b64decode(data).decode("utf-8")
        status = ""
        try:
            status = r.json().get("error", {}).get("status", "")
        except ValueError:
            pass
        if r.status_code == 404 or status in ("NOT_FOUND", "FAILED_PRECONDITION"):
            return None  # created empty / no enabled version yet
        raise StartupError(
            f"Secret Manager: {secret_id}: HTTP {r.status_code} {status}".strip()
        )


_creds = None


def _adc_token() -> str:
    global _creds
    import google.auth
    from google.auth.transport.requests import Request

    if _creds is None:
        _creds, _ = google.auth.default(scopes=[CLOUD_PLATFORM])
    if not _creds.valid:
        _creds.refresh(Request())
    return _creds.token


def default_project() -> str | None:
    import google.auth

    _, project = google.auth.default(scopes=[CLOUD_PLATFORM])
    return project


def load_secrets(env: dict, accessor, project: str) -> list[str]:
    loaded = []
    for var, sid in parse_spec(env.get(SPEC_ENV, "")):
        if env.get(var):
            logger.info("%s already set; not reading secret %s", var, sid)
            continue
        value = accessor(project, sid)
        if value is None:
            logger.info("Secret %s has no version; %s left unset", sid, var)
            continue
        env[var] = value.rstrip("\r\n")
        loaded.append(var)
    return loaded


def validate(env: dict) -> None:
    if not env.get("JWT_SECRET_KEY", "").strip():
        raise StartupError(
            "JWT_SECRET_KEY is empty: add a version to the jwt-secret-key secret "
            "(or set it in the environment). Refusing to start."
        )


def _forwarded(value: str) -> str:
    items = [v.strip() for v in value.split(",") if v.strip()]
    if not items:
        raise StartupError("FORWARDED_ALLOW_IPS is empty")
    for item in items:
        try:
            net = ipaddress.ip_network(item, strict=False)
        except ValueError:
            raise StartupError(
                f"FORWARDED_ALLOW_IPS: {item!r} is not an IP or network "
                '("*" is never allowed)'
            ) from None
        if net.prefixlen == 0:
            raise StartupError(f"FORWARDED_ALLOW_IPS: {item!r} trusts everyone")
    return ",".join(items)


def uvicorn_argv(env: dict) -> list[str]:
    host = env.get("HOST", "0.0.0.0")  # nosec B104 — inside the container
    argv = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        env.get("PORT", "8001"),
        "--workers",
        "1",
        "--timeout-graceful-shutdown",
        env.get("GRACEFUL_SHUTDOWN_SECONDS", "5"),
    ]
    if env.get("FORWARDED_ALLOW_IPS", "").strip():
        argv += [
            "--proxy-headers",
            f"--forwarded-allow-ips={_forwarded(env['FORWARDED_ALLOW_IPS'])}",
        ]
    else:
        argv.append("--no-proxy-headers")
    return argv


def main(env: dict | None = None, accessor=None, execve=os.execve) -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    env = dict(os.environ) if env is None else env
    try:
        if env.get(SPEC_ENV, "").strip():
            project = (
                env.get("GOOGLE_CLOUD_PROJECT")
                or env.get("GCP_PROJECT")
                or default_project()
            )
            if not project:
                raise StartupError("no GCP project for Secret Manager")
            env.setdefault("GOOGLE_CLOUD_PROJECT", project)
            loaded = load_secrets(env, accessor or SecretManagerAccessor(), project)
            logger.info("Loaded %d secret(s) into the environment", len(loaded))
        validate(env)
        argv = uvicorn_argv(env)
    except StartupError as exc:
        print(f"entrypoint: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    execve(argv[0], argv, env)


if __name__ == "__main__":  # pragma: no cover
    main()
