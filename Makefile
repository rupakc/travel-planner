.PHONY: install install-hooks format lint security test ci

install:          ## Install backend + frontend dependencies
	pip install -r backend/requirements.txt -r backend/requirements-dev.txt
	cd frontend && npm ci

install-hooks:    ## Wire pre-commit hooks (run once after cloning)
	pre-commit install
	@echo "✓ pre-commit hooks installed — formatting runs automatically on git commit"

format:           ## Auto-format Python (ruff). Run before committing if hooks are not installed.
	cd backend && ruff format . && ruff check --fix .

lint:             ## Run all linters (mirrors CI lint jobs)
	cd backend && ruff check . && ruff format --check .
	cd frontend && npx eslint src/ --max-warnings 0

security:         ## Run security scans (mirrors CI security job)
	bandit -r backend/app/ -ll --skip B105,B106,B608
	pip-audit -r backend/requirements.txt --timeout 60 --ignore-vuln PYSEC-2023-62
	cd frontend && npm audit --audit-level=high

test:             ## Run backend + frontend tests (mirrors CI test jobs)
	cd backend && DATA_DIR=/tmp/test-data ADMIN_PASSWORD=test-admin-pw \
	  pytest --cov=app --cov-report=term-missing -q
	cd frontend && npm run test:coverage

ci: lint security test  ## Full local CI check — run this before pushing
