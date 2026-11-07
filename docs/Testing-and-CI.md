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
| `test-deploy-kit` | `pytest deploy/gcp/tests deploy/ci/tests infrastructure/gcp/tests` (governor, deployer with fakes, the deploy workflow's scripts, old-prod migration, `bootstrap.sh`). Its own job so it runs in parallel with `test-backend` (together they took 4–6 min) |
| `host-checks` | The VM kit's host layer (see below) |
| `image-builds` | Builds (nothing pushed), in parallel with the rest, the images whose inputs the change touches: the app (`backend/`, `.agents/`) and Caddy + SPA (`frontend/`, `deploy/gcp/Caddyfile`, `caddy.Dockerfile`), each then **Trivy-scanned with the deploy policy** (`deploy/ci/trivy-scan.sh`), and the local-only nginx `frontend/Dockerfile` (its own files and `package*.json`; build only, it doesn't ship). It reads the deploy workflow's BuildKit cache. A push with no usable base, or a change to `ci.yml`, `deploy.yml` or a `deploy/ci` script, does all three. Skipped when `deploy.yml` calls CI (`skip-image-builds`): its build jobs build and scan the images that ship |

### docs.yml

Runs on push to `main` and by hand. Installs `mkdocs`, `mkdocstrings[python]`, `mkdocs-material` and `ghp-import`, runs `mkdocs build` from `mkdocs.yml`, **copies `docs_homepage/index.html` over `site/index.html`**, and publishes `site/` to the `gh-pages` branch, served at https://rupakc.github.io/travel-planner/. The custom homepage therefore replaces `docs/index.md` at the site root; the docs pages live under it (for example `/Home/`, `/Architecture/`).

To check the docs locally:

```bash
pip install mkdocs mkdocs-material "mkdocstrings[python]"
mkdocs build --strict      # or: mkdocs serve
```

### deploy.yml

Runs on every push to `main`, **weekly** (Mondays 04:17 UTC, a no-cache refresh of both images) and by hand (`workflow_dispatch`, input `force`, default on). One run at a time (runs queue, a tag is never half-moved). The two images are independent, so a Caddy failure never blocks an app fix and vice versa:

```
ci ─────────────┬──► promote-app    (needs ci + build-app)
build-app ──────┘
ci ─────────────┬──► promote-caddy  (needs ci + build-caddy)
build-caddy ────┘
```

- **`ci`** calls `ci.yml` as a reusable workflow (`contents: read`; plain pushes to `main` don't run CI twice). Its `image-builds` job is skipped here.
- **`build-app`, `build-caddy`** run **in parallel with `ci`** (`contents: read`, `packages: write`; no `id-token`, so they can't sign). Each:
  1. pins its base images to their current digests (`PYTHON_BASE`; `CADDY_BASE` and the SPA builder's `NODE_BASE`) and computes the image's **inputs id** with `deploy/ci/image-inputs-id.sh`: a SHA-256 over the Dockerfile, `.dockerignore`, every file the Dockerfile's `COPY`s take from the context (derived from the Dockerfile itself) and the pinned bases;
  2. `deploy/ci/build-decision.sh` reads the label `io.voyager.app-inputs` / `io.voyager.caddy-inputs` of the image `prod` points at. Equal → nothing is built and `prod` stays (a frontend-only merge doesn't restart the app; a backend-only merge doesn't touch the SPA; a docs-only merge publishes nothing). Missing, unreadable or different → build. A forced run, or a `prod` image whose `io.voyager.fresh-at` is missing or over 7 days old → refresh (build with `no-cache`). An id that can't be computed is empty and also builds: `ADD`, a JSON or heredoc `COPY`, a variable in a source, `COPY --from`/`--mount from=` naming anything but an earlier stage, a `--mount` without `type=` or a bind mount of the context (type in any case), a `FROM` that is neither an earlier stage, a pinned build arg passed as `NAME=ref@sha256:…` nor an image pinned by digest, and `.dockerignore` re-includes other than `!**/NAME` (those switch all exclusions off instead; `!**/NAME` re-includes files and directories named NAME);
  3. builds and pushes a `sha-<commit>` tag;
  4. scans it **by digest** with `deploy/ci/trivy-scan.sh` (Trivy 0.70.0, checksum-pinned): any fixed CRITICAL finding fails (`.trivyignore` lists accepted ones).
- **`promote-app`, `promote-caddy`** have a plain `needs: [ci, build-<image>]`, so each is **skipped unless both succeeded** (no `always()`). They are the only jobs with `id-token: write` (plus `contents: read`, `packages: write`) and run `deploy/ci/promote-image.sh`:
  1. `main`'s HEAD must be a 40-hex SHA (else fail). If it isn't this commit, stop: nothing is signed, `prod` doesn't move;
  2. a built image is signed with **cosign keyless** (GitHub OIDC → Sigstore), verified with the identity the VM requires, then `prod` moves to it and must resolve to exactly that digest;
  3. a skipped image is not signed again; `prod` must still be the digest the build job compared, else the job fails.

  So every image signed as `deploy.yml@refs/heads/main` has passed CI and was `main`'s HEAD when signed. Scheduled and dispatched runs on `main` sign with the same identity: the certificate carries the workflow file and ref (`job_workflow_ref`), not the event. Every job is skipped unless `github.ref` is `refs/heads/main`.

Building before CI has passed is safe: the image stays unsigned under its `sha-` tag, the VM refuses unsigned images, and it only ever deploys the digest the `prod` tag points at. `deploy.sh` compares each image's `io.voyager.build` only with its own predecessor (the running app; the live SPA release), so promoting one image while the other keeps an older run number is not a downgrade.

**Not in the inputs id:** what a `RUN` step resolves at build time, i.e. pip resolving the version ranges in `backend/requirements.txt` (npm follows `package-lock.json`). The weekly **refresh** picks up those and any new base image: forced builds run with `no-cache`, and their new digests also end a hold on the VM. It restarts the app once a week (after draining open streams). Each image carries `io.voyager.fresh-at` (the time of its last refresh, carried forward by cached builds), and `build-decision.sh` refreshes an image on *any* run when `prod`'s value is missing or over 7 days old, so a dropped scheduled run (replaced by a queued push) or a schedule GitHub disabled after 60 days of repository inactivity (`gh workflow enable deploy.yml` / `prod-scan.yml` re-enables them) doesn't stop refreshes.

Every action in every workflow is pinned to a full commit SHA, with a version comment, because the promote jobs can sign as the identity the VM trusts. Images carry the label `io.voyager.build` (the workflow run number), and the VM refuses an image from an older run than the one it is running.

### prod-scan.yml

Daily (05:41 UTC) and by hand: `deploy/ci/trivy-scan.sh` on `ghcr.io/rupakc/travel-planner-app:prod` and `…-caddy:prod`, with the same policy. A finding makes the run fail (a GitHub notification); it never signs or moves anything. Ship the fix by merging it or by running Deploy by hand.

It has no GCP or VM credentials: the VM pulls and verifies by itself (see [Deployment on GCP](Deployment-GCP.md#6-day-to-day-deploys-and-rollback)).

The `host-checks` job runs `deploy/gcp/tests/host_checks.sh` in `debian:trixie` (pinned by digest, `NET_ADMIN`). It checks four things:

1. **Governor rules:** the real rules on iptables-nft for every tier, and that a rejected ruleset leaves the old rules intact.
2. **Deployer:** `deploy/gcp/tests/test_deploy.py` drives `deploy.sh` end to end with fake docker, curl and systemctl (`deploy_fakes.py`). It runs here as root and again in `test-deploy-kit` as a normal user; it is skipped off Linux. App scenarios: first deploy, upgrade, manual rollback with a hold, a newer digest ending the hold, automatic rollback, and downgrade refusal (remembered), plus `voyager.service` started with `--no-block`. Edge scenarios: an SPA-only swap (no restart; asserts the absence of recreate and reload), a Caddyfile hot reload, an invalid Caddyfile, a reload failure, a failed post-switch check, a symlink or missing asset in the image, pruning to three releases with older assets still reachable, a runtime change (drain, recreate, checks), the drain timeout, a runtime rollback, Caddy downgrades, signature failure, a `compose.yaml` change drained, GHCR `429` back-off, the cheap no-change run, `--rollback-edge` (and toggling it back), `--rollback-caddy`, `--window`, migration from the old `images.env` (with and without the new image) and a lost edge directory. The fakes can make `docker pull`, `create`, `cp`, `compose up` (failing, or exiting 0 while leaving the old container) and `caddy adapt` fail. The tests then check that infrastructure failures hold nothing and retry, that a failed pull never skips the downgrade check, that a held runtime ships content only, that a broken edge never blocks the app, that emails are rate-limited, that a no-change run makes exactly one `docker ps`, and that `step` stops a function at its first failing command.
3. **First boot:** `first-boot.sh` for real with fake curl, docker and systemctl (`first_boot_sim.sh`), on a first and a later boot: `voyager.service` ends up active, voyager units are only started with `--no-block`, and the bundle (built by `bootstrap.sh`) unpacks without tar warnings.
4. **systemd units:** `systemd-analyze verify`.

CI also runs `shellcheck` on `deploy/gcp/*.sh`, `deploy/gcp/host/*.sh`, `deploy/ci/*.sh` and `infrastructure/gcp/*.sh`, ruff on `deploy/` and `infrastructure/gcp/`, and the tests in `deploy/gcp/tests` (egress governor, the deployer), `deploy/ci/tests` (`build-decision.sh` and `promote-image.sh` against fake docker/git/cosign: skip only on an equal label, sign → verify → move in that order, never sign a skipped or superseded image, fail closed on an unreadable HEAD or digest; `image-inputs-id.sh`: same inputs give the same id regardless of order and mtime; any change to a source, `requirements.txt`, `.agents/`, the Dockerfile, `.dockerignore`, the base, an executable bit, a new, deleted or renamed file changes it; `.dockerignore`d, gitignored and un-`COPY`ed files don't; unsupported Dockerfiles, foreign `--from` and context mounts fail; unusual re-includes switch exclusions off; and the real app and Caddy input lists) and `infrastructure/gcp/tests` (old-prod migration; `bootstrap.sh` against stub gcloud/curl: dry run calls nothing, beta preflight, billing quota project, clean sorted host bundle).
