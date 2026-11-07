# Testing and CI

---

## Backend tests

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt   # pytest, pytest-asyncio, pytest-cov, ruff, bandit, pip-audit
python3 -m pytest -q
```

- `tests/conftest.py` points `DATA_DIR` at a temporary directory (deleted at exit), sets a JWT secret, `RATE_LIMIT_ENABLED=false` and an empty `BACKUP_BUCKET`, and seeds the place data once per session.
- `pyproject.toml` sets `asyncio_mode = "auto"`. An autouse fixture replaces the Gemini and Anthropic clients in `core/llm.py` with stubs, so tests never reach a model; tests that need replies fake `llm.generate` / `llm.stream` or the client (`tests/test_llm.py`). `scripts/llm_eval.py`, which does call the real model, is never run by CI (it refuses when `CI` is set).
- `tests/test_golden_places_runtime.py` runs the 693-case golden set (`tests/data/golden_places.csv`) against place resolution and autocomplete and forbids web calls. `tests/test_build_place_data.py` checks the place-data generator. See [Place and Airport Data](Place-and-Airport-Data.md#quality).
- Coverage, as CI runs it:

  ```bash
  DATA_DIR=/tmp/test-data ADMIN_PASSWORD=test-admin-pw \
    python3 -m pytest --cov=app --cov-report=xml --cov-fail-under=70
  ```

  Coverage omits the agent classes, the orchestrator and chat agent, `static_results.py`, `web_tools.py`, `schemas/travel.py`, the seeders, `backup.py` and `database.py`.

As of 2026-10-30: 3,794 passed, 1 skipped.

## Frontend tests

```bash
cd frontend
npm test                    # vitest run --passWithNoTests
npm run test:coverage       # with v8 coverage, as CI runs it
```

Tests are `*.test.js(x)` files next to the code, run with vitest in jsdom (configured in `vite.config.js`). On Node 20.18 vitest needs `NODE_OPTIONS=--experimental-require-module`:

```bash
NODE_OPTIONS=--experimental-require-module npx vitest run
```

As of 2026-10-30: 38 test files, 532 tests passed.

## Lint and format

| Check | Command |
|---|---|
| Backend lint | `ruff check backend/` |
| Backend format | `ruff format --check backend/` |
| Frontend lint | `cd frontend && npx eslint src/ --max-warnings 0` |

Ruff 0.15.13 is pinned and selects E, W, F, I and UP (ignoring E501 and UP007). The ESLint config (`frontend/eslint.config.js`) has one substantive rule: lucide icons whose names shadow globals (Map, Image, History, Text, Option, Infinity, Navigation) must be imported under an alias, because a shadowed `Map` once crashed every multi-city search. There is no `lint` npm script.

**Pre-commit** (`.pre-commit-config.yaml`, install with `make install-hooks`): ruff lint (`--fix`) and format on `backend/`, trailing whitespace, end-of-file, merge-conflict markers, YAML/JSON checks and mixed line endings.

**Makefile** targets (run from the repo root): `install` (backend requirements plus `npm ci`), `install-hooks`, `format`, `lint` (ruff and ESLint), `security` (bandit, pip-audit, npm audit), `test` (both suites with coverage), and `ci` (lint + security + test). Note that `make security` still ignores PYSEC-2025-185 and PYSEC-2025-183, which CI no longer ignores.

---

## Workflows

All in `.github/workflows/`.

### ci.yml

Runs on every push to any branch and on pull requests to `main`.

| Job | What it does |
|---|---|
| `lint-backend` | ruff check and ruff format --check |
| `lint-frontend` | eslint with `--max-warnings 0` |
| `security` | bandit `-ll --skip B105,B106,B608`; pip-audit (ignoring PYSEC-2023-62); `npm audit --audit-level=high` |
| `test-backend` | Python 3.12, pytest with coverage ≥ 70% |
| `test-frontend` | Node 20, `npm run test:coverage` |
| `build-and-scan` | Needs all of the above. Builds both images (`docker build -f backend/Dockerfile .` and `docker build frontend/`) and scans them with Trivy 0.70.0, failing on unfixed CRITICAL findings (`.trivyignore` lists accepted ones) |

### docs.yml

Runs on push to `main` and by hand. Installs `mkdocs`, `mkdocstrings[python]`, `mkdocs-material` and `ghp-import`, runs `mkdocs build` from `mkdocs.yml`, **copies `docs_homepage/index.html` over `site/index.html`**, and publishes `site/` to the `gh-pages` branch, served at https://rupakc.github.io/travel-planner/. The custom homepage therefore replaces `docs/index.md` at the site root; the docs pages live under it (for example `/Home/`, `/Architecture/`).

To check the docs locally:

```bash
pip install mkdocs mkdocs-material "mkdocstrings[python]"
mkdocs build --strict      # or: mkdocs serve
```

### deploy.yml

Runs on every push to `main`. It calls `ci.yml` as a reusable workflow, so every CI job must pass first; plain pushes to `main` don't run CI twice. Then one `publish` job runs with only `contents: read`, `packages: write` and `id-token: write`. It:

1. builds the app image (`backend/Dockerfile`) and the Caddy + SPA image (`deploy/gcp/caddy.Dockerfile`);
2. pushes them to GHCR with `sha-<commit>` tags;
3. signs both digests with **cosign keyless** (GitHub OIDC → Sigstore) and verifies them with the identity the VM requires;
4. moves the `prod` tags to those digests with `docker buildx imagetools create`, checks that each tag resolves to exactly the signed digest, and does so only if the commit is still `main`'s HEAD.

Every action in every workflow is pinned to a full commit SHA, with a version comment, because this job can sign as the identity the VM trusts. Images carry the label `io.voyager.build` (the workflow run number), and the VM refuses an image from an older run than the one it is running.

It has no GCP or VM credentials: the VM pulls and verifies by itself (see [Deployment on GCP](Deployment-GCP.md#6-day-to-day-deploys-and-rollback)).

The `host-checks` job runs `deploy/gcp/tests/host_checks.sh` in `debian:trixie` (pinned by digest, `NET_ADMIN`). It checks four things:

1. **Governor rules:** the real rules on iptables-nft for every tier, and that a rejected ruleset leaves the old rules intact.
2. **Deployer:** `deploy/gcp/tests/test_deploy.py` drives `deploy.sh` end to end with fake docker, curl and systemctl (`deploy_fakes.py`). It runs here as root and again in `test-backend`'s deploy-kit step as a normal user; it is skipped off Linux. App scenarios: first deploy, upgrade, manual rollback with a hold, a newer digest ending the hold, automatic rollback, and downgrade refusal (remembered), plus `voyager.service` started with `--no-block`. Edge scenarios: an SPA-only swap (no restart; asserts the absence of recreate and reload), a Caddyfile hot reload, an invalid Caddyfile, a reload failure, a failed post-switch check, a symlink or missing asset in the image, pruning to three releases with older assets still reachable, a runtime change (drain, recreate, checks), the drain timeout, a runtime rollback, Caddy downgrades, signature failure, a `compose.yaml` change drained, GHCR `429` back-off, the cheap no-change run, `--rollback-edge` (and toggling it back), `--rollback-caddy`, `--window`, migration from the old `images.env` (with and without the new image) and a lost edge directory. The fakes can make `docker pull`, `create`, `cp`, `compose up` (failing, or exiting 0 while leaving the old container) and `caddy adapt` fail. The tests then check that infrastructure failures hold nothing and retry, that a failed pull never skips the downgrade check, that a held runtime ships content only, that a broken edge never blocks the app, that emails are rate-limited, that a no-change run makes exactly one `docker ps`, and that `step` stops a function at its first failing command.
3. **First boot:** `first-boot.sh` for real with fake curl, docker and systemctl (`first_boot_sim.sh`), on a first and a later boot: `voyager.service` ends up active, voyager units are only started with `--no-block`, and the bundle (built by `bootstrap.sh`) unpacks without tar warnings.
4. **systemd units:** `systemd-analyze verify`.

The image build waits for it. CI also runs `shellcheck` on `deploy/gcp/*.sh`, `deploy/gcp/host/*.sh` and `infrastructure/gcp/*.sh`, ruff on `deploy/` and `infrastructure/gcp/`, and the tests in `deploy/gcp/tests` (egress governor) and `infrastructure/gcp/tests` (old-prod migration; `bootstrap.sh` against stub gcloud/curl: dry run calls nothing, beta preflight, billing quota project, clean sorted host bundle).
