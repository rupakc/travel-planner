"""Container entrypoint: secrets from Secret Manager into the process env
(never a file), refuse to start without a JWT key, and build the uvicorn
command (proxy headers trusted only from explicit networks, never "*").

No network: the Secret Manager accessor is a fake.
"""

import sys

import httpx
import pytest

from app import entrypoint


class FakeAccessor:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def __call__(self, project, secret_id):
        self.calls.append((project, secret_id))
        return self.values.get(secret_id)


def test_spec_parsing_derives_secret_ids():
    assert entrypoint.parse_spec("JWT_SECRET_KEY, SERPAPI_KEY=serp-key,,") == [
        ("JWT_SECRET_KEY", "jwt-secret-key"),
        ("SERPAPI_KEY", "serp-key"),
    ]


@pytest.mark.parametrize("bad", ["lower_case", "A=B=C", "X=", "1ABC"])
def test_spec_rejects_malformed_entries(bad):
    with pytest.raises(entrypoint.StartupError):
        entrypoint.parse_spec(bad)


def test_secrets_land_in_env_with_trailing_newline_stripped():
    env = {"SECRET_MANAGER_SECRETS": "JWT_SECRET_KEY,SMTP_PASSWORD"}
    acc = FakeAccessor({"jwt-secret-key": "k" * 40 + "\n", "smtp-password": "pw"})
    loaded = entrypoint.load_secrets(env, acc, "proj-1")
    assert env["JWT_SECRET_KEY"] == "k" * 40
    assert env["SMTP_PASSWORD"] == "pw"
    assert loaded == ["JWT_SECRET_KEY", "SMTP_PASSWORD"]
    assert acc.calls == [("proj-1", "jwt-secret-key"), ("proj-1", "smtp-password")]


def test_secret_without_a_version_is_skipped():
    env = {"SECRET_MANAGER_SECRETS": "SERPAPI_KEY"}
    assert entrypoint.load_secrets(env, FakeAccessor({}), "p") == []
    assert "SERPAPI_KEY" not in env


def test_explicit_env_wins_over_secret_manager():
    env = {"SECRET_MANAGER_SECRETS": "SERPAPI_KEY", "SERPAPI_KEY": "local"}
    acc = FakeAccessor({"serpapi-key": "remote"})
    entrypoint.load_secrets(env, acc, "p")
    assert env["SERPAPI_KEY"] == "local"
    assert acc.calls == []


@pytest.mark.parametrize("value", [None, "", "   "])
def test_refuses_to_start_without_jwt_key(value):
    env = {} if value is None else {"JWT_SECRET_KEY": value}
    with pytest.raises(entrypoint.StartupError, match="JWT_SECRET_KEY"):
        entrypoint.validate(env)


def test_uvicorn_argv_defaults():
    argv = entrypoint.uvicorn_argv({})
    assert argv[:3] == [sys.executable, "-m", "uvicorn"]
    assert "app.main:app" in argv
    assert argv[argv.index("--port") + 1] == "8001"
    assert argv[argv.index("--workers") + 1] == "1"
    assert argv[argv.index("--timeout-graceful-shutdown") + 1] == "5"
    assert "--no-proxy-headers" in argv
    assert not any(a.startswith("--forwarded-allow-ips") for a in argv)


def test_uvicorn_argv_trusts_only_the_compose_network():
    argv = entrypoint.uvicorn_argv({"FORWARDED_ALLOW_IPS": "172.30.0.0/24"})
    assert "--proxy-headers" in argv
    assert "--forwarded-allow-ips=172.30.0.0/24" in argv


@pytest.mark.parametrize("bad", ["*", "172.30.0.0/24,*", "not-an-ip", "0.0.0.0/0"])
def test_uvicorn_argv_refuses_wildcards_and_junk(bad):
    with pytest.raises(entrypoint.StartupError):
        entrypoint.uvicorn_argv({"FORWARDED_ALLOW_IPS": bad})


def test_main_execs_uvicorn_with_secrets_in_env_only(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    seen = {}

    def fake_exec(path, argv, env):
        seen.update(path=path, argv=argv, env=env)

    env = {
        "SECRET_MANAGER_SECRETS": "JWT_SECRET_KEY",
        "GOOGLE_CLOUD_PROJECT": "voyager-test",
        "FORWARDED_ALLOW_IPS": "172.30.0.0/24",
    }
    acc = FakeAccessor({"jwt-secret-key": "s" * 48})
    entrypoint.main(env=env, accessor=acc, execve=fake_exec)
    assert seen["env"]["JWT_SECRET_KEY"] == "s" * 48
    assert seen["path"] == sys.executable
    assert "--forwarded-allow-ips=172.30.0.0/24" in seen["argv"]
    assert list(tmp_path.iterdir()) == []  # nothing written to disk


def test_main_resolves_the_project_and_exports_it(monkeypatch):
    seen = {}
    monkeypatch.setattr(entrypoint, "default_project", lambda: "from-metadata")
    env = {"SECRET_MANAGER_SECRETS": "JWT_SECRET_KEY"}
    acc = FakeAccessor({"jwt-secret-key": "x" * 40})
    entrypoint.main(env=env, accessor=acc, execve=lambda p, a, e: seen.update(env=e))
    assert acc.calls == [("from-metadata", "jwt-secret-key")]
    assert seen["env"]["GOOGLE_CLOUD_PROJECT"] == "from-metadata"


def test_main_exits_nonzero_without_jwt(capsys):
    with pytest.raises(SystemExit) as exc:
        entrypoint.main(env={}, accessor=FakeAccessor({}), execve=lambda *a: None)
    assert exc.value.code == 1
    assert "JWT_SECRET_KEY" in capsys.readouterr().err


def test_main_without_spec_needs_no_google_credentials():
    seen = {}
    entrypoint.main(
        env={"JWT_SECRET_KEY": "y" * 40},
        accessor=None,
        execve=lambda p, a, e: seen.update(ok=True),
    )
    assert seen["ok"]


# ── Secret Manager REST accessor ─────────────────────────────────────────────


def _transport(status, body):
    def handler(request: httpx.Request):
        assert request.headers["authorization"] == "Bearer tok"
        assert request.url.path == (
            "/v1/projects/p/secrets/jwt-secret-key/versions/latest:access"
        )
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def test_accessor_decodes_the_payload():
    acc = entrypoint.SecretManagerAccessor(
        token=lambda: "tok",
        transport=_transport(200, {"payload": {"data": "c2VjcmV0"}}),
    )
    assert acc("p", "jwt-secret-key") == "secret"


@pytest.mark.parametrize(
    "status,body",
    [
        (404, {"error": {"status": "NOT_FOUND"}}),
        (400, {"error": {"status": "FAILED_PRECONDITION"}}),
    ],
)
def test_accessor_treats_missing_or_disabled_versions_as_unset(status, body):
    acc = entrypoint.SecretManagerAccessor(
        token=lambda: "tok", transport=_transport(status, body)
    )
    assert acc("p", "jwt-secret-key") is None


def test_accessor_raises_on_permission_errors():
    acc = entrypoint.SecretManagerAccessor(
        token=lambda: "tok",
        transport=_transport(403, {"error": {"status": "PERMISSION_DENIED"}}),
    )
    with pytest.raises(entrypoint.StartupError, match="403"):
        acc("p", "jwt-secret-key")
