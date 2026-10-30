# Testing and CI

---

## Backend tests

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt   # pytest, pytest-asyncio, pytest-cov, ruff, bandit, pip-audit
python3 -m pytest -q
```

- `tests/conftest.py` points `DATA_DIR` at a temporary directory (deleted at exit), sets a JWT secret, `RATE_LIMIT_ENABLED=false` and an empty `BACKUP_BUCKET`, and seeds the place data once per session.
- `pyproject.toml` sets `asyncio_mode = "auto"`. Tests mock the Anthropic API; they make no real LLM calls.
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

Manual only and marked decommissioned. See [Deployment](Deployment.md).
