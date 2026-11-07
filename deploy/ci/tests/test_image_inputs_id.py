"""image-inputs-id.sh: the content id the deploy workflow compares with the
`prod` image's io.voyager.inputs label to skip a build (and the VM's restart).

The rule that matters: any change the image could see changes the id
(under-counting would ship a stale image); changes it can't see may or may
not. Anything the script can't account for exactly must fail (the workflow
then builds).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "image-inputs-id.sh"
REPO = HERE.parent.parent.parent

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

DOCKERFILE = """\
ARG PYTHON_BASE=python:3.12-slim
FROM ${PYTHON_BASE}
WORKDIR /app
# a comment
COPY backend/requirements.txt .
RUN pip install -r requirements.txt \\
    && echo done
COPY --chown=1:1 backend/ ./
COPY .agents/ .agents/
CMD ["python", "-m", "app"]
"""

DOCKERIGNORE = """\
.git
**/__pycache__
**/.env
!**/.env.example
backend/tests
/backend/data/
docs
"""

FILES = {
    "backend/Dockerfile": DOCKERFILE,
    ".dockerignore": DOCKERIGNORE,
    ".gitignore": "*.log\n",
    "backend/requirements.txt": "fastapi\n",
    "backend/app/main.py": "print('hi')\n",
    "backend/app/core/x.py": "X = 1\n",
    "backend/tests/test_x.py": "def test(): pass\n",
    "backend/tests/.env.example": "A=1\n",
    "backend/data/seed.csv": "a,b\n",
    ".agents/flights.md": "---\nname: flights\n---\nprompt\n",
    "frontend/src/App.jsx": "export default 1\n",
    "docs/Home.md": "# Home\n",
}


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def make_repo(root: Path, files: dict[str, str] = FILES, order=None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    for name in order or files:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(files[name])
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    return root


def run(root: Path, *args: str, dockerfile="backend/Dockerfile"):
    return subprocess.run(
        ["bash", str(SCRIPT), dockerfile, *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def ident(root: Path, *args: str, dockerfile="backend/Dockerfile") -> str:
    r = run(root, *args, dockerfile=dockerfile)
    assert r.returncode == 0, r.stderr
    out = r.stdout.strip()
    assert len(out) == 64 and int(out, 16) >= 0
    return out


def listed(root: Path, dockerfile="backend/Dockerfile") -> list[str]:
    r = subprocess.run(
        ["bash", str(SCRIPT), "--list", dockerfile],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return [
        line.split()[-1]
        for line in r.stdout.splitlines()
        if line.startswith(("file ", "link "))
    ]


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "r")


def test_same_inputs_same_id_regardless_of_order_and_mtime(repo, tmp_path):
    a = ident(repo, "base@sha256:1")
    assert ident(repo, "base@sha256:1") == a
    other = make_repo(tmp_path / "other", order=list(reversed(list(FILES))))
    for p in other.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            os.utime(p, (1_000_000, 1_000_000))
    assert ident(other, "base@sha256:1") == a


@pytest.mark.parametrize(
    "change",
    [
        lambda r: (r / "backend/app/main.py").write_text("print('bye')\n"),
        lambda r: (r / "backend/requirements.txt").write_text("fastapi==1\n"),
        lambda r: (r / ".agents/flights.md").write_text("changed\n"),
        lambda r: (r / "backend/Dockerfile").write_text(
            DOCKERFILE.replace("WORKDIR /app", "WORKDIR /srv")
        ),
        lambda r: (r / ".dockerignore").write_text(DOCKERIGNORE + "backend/app/core\n"),
        lambda r: (r / "backend/app/new.py").write_text(
            "NEW = 1\n"
        ),  # untracked, not ignored
        lambda r: (r / "backend/app/core/x.py").unlink(),
        lambda r: (r / "backend/app/core/x.py").chmod(0o755),
        lambda r: os.rename(r / "backend/app/core/x.py", r / "backend/app/core/y.py"),
        lambda r: (r / "backend/tests/.env.example").write_text(
            "A=2\n"
        ),  # re-included by `!`
    ],
    ids=[
        "source",
        "requirements",
        "agents",
        "dockerfile",
        "dockerignore",
        "new-file",
        "deleted-file",
        "exec-bit",
        "renamed-file",
        "negated-ignore",
    ],
)
def test_any_input_change_changes_the_id(repo, change):
    before = ident(repo, "base@sha256:1")
    change(repo)
    assert ident(repo, "base@sha256:1") != before


def test_extra_inputs_count(repo):
    assert ident(repo, "base@sha256:1") != ident(repo, "base@sha256:2")
    assert ident(repo, "base@sha256:1") != ident(repo)


@pytest.mark.parametrize(
    "change",
    [
        lambda r: (r / "backend/tests/test_x.py").write_text(
            "changed\n"
        ),  # .dockerignore'd
        lambda r: (r / "backend/data/seed.csv").write_text(
            "changed\n"
        ),  # .dockerignore'd
        lambda r: (r / "frontend/src/App.jsx").write_text("changed\n"),  # not COPYed
        lambda r: (r / "docs/Home.md").write_text("changed\n"),
        lambda r: (r / "backend/app/debug.log").write_text("gitignored\n"),
        lambda r: os.utime(r / "backend/app/main.py", (1, 1)),
    ],
    ids=["tests", "ignored-dir", "frontend", "docs", "gitignored", "mtime"],
)
def test_changes_outside_the_image_keep_the_id(repo, change):
    before = ident(repo, "base@sha256:1")
    change(repo)
    assert ident(repo, "base@sha256:1") == before


@pytest.mark.parametrize(
    "dockerfile",
    [
        "FROM x\nADD backend/ /app\n",
        "FROM x\nCOPY $SRC /app\n",
        'FROM x\nCOPY ["backend/", "/app"]\n',
        "FROM x\nCOPY <<EOF /a\nhi\nEOF\n",
        "FROM x\nRUN --mount=type=bind,target=/src make\n",
        "FROM x\nCOPY nothing-here/ /app\n",
        "FROM x\nRUN echo no copy\n",
    ],
    ids=["add", "variable", "json", "heredoc", "bind-mount", "no-match", "no-copy"],
)
def test_unsupported_dockerfiles_fail_so_the_workflow_builds(repo, dockerfile):
    (repo / "backend/Dockerfile").write_text(dockerfile)
    r = run(repo)
    assert r.returncode != 0
    assert r.stdout == ""


def test_stage_copies_and_bind_mounts_from_stages_are_not_context(repo):
    (repo / "backend/Dockerfile").write_text(
        "FROM x AS a\nCOPY .agents/ /a\nFROM y\n"
        "RUN --mount=type=bind,from=a,target=/a ls\nCOPY --from=a /a /b\n"
    )
    assert listed(repo) == [".agents/flights.md"]


def test_dockerfile_specific_ignore_file_disables_root_exclusions(repo):
    (repo / "backend/Dockerfile.dockerignore").write_text(".git\n")
    assert "backend/tests/test_x.py" in listed(repo)


def test_real_app_image_inputs():
    files = listed(REPO, "backend/Dockerfile")
    assert "backend/requirements.txt" in files
    assert "backend/app/main.py" in files
    assert ".agents/flights.md" in files
    assert not [f for f in files if f.startswith("backend/tests/")]
    assert not [f for f in files if f.startswith(("frontend/", "docs/", "deploy/"))]


def test_real_caddy_image_inputs():
    files = listed(REPO, "deploy/gcp/caddy.Dockerfile")
    assert "frontend/package.json" in files
    assert "frontend/package-lock.json" in files
    assert "frontend/index.html" in files
    assert "deploy/gcp/Caddyfile" in files
    assert not [f for f in files if f.startswith(("backend/", ".agents/", "docs/"))]
