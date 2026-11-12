"""Shared fixtures for the test suite.

Env vars must be set at module level (before any app imports) so pydantic-settings
reads them during Settings() instantiation at collection time.
"""

import atexit
import os
import shutil
import tempfile

# ─── Set test env vars BEFORE any app imports ─────────────────────────────────
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="tp_test_")
# The session DB holds the whole place dataset (~23 MB): never leave it behind.
atexit.register(shutil.rmtree, _TEST_DATA_DIR, ignore_errors=True)
os.environ.setdefault("DATA_DIR", _TEST_DATA_DIR)
os.environ["ADMIN_PASSWORD"] = "test-admin-pw!"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-at-least-32-bytes-long!"
os.environ["LOG_FORMAT"] = "text"
os.environ["BACKUP_BUCKET"] = ""
os.environ["RATE_LIMIT_ENABLED"] = "false"  # tests opt in via test_rate_limit
os.environ["AI_DAILY_QUOTA_ENABLED"] = "false"  # tests opt in via test_ai_quota
os.environ["FARE_WATCH_ENABLED"] = "false"  # never start the real scheduler loop
os.environ["SMTP_HOST"] = ""  # never send real email
# default False is tested in test_signup_needs_operator_opt_in
os.environ["SIGNUP_ENABLED"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import llm as _llm  # noqa: E402

# LLM_PROVIDER=auto never asks the machine's real ADC for a project (that can
# reach the GCE metadata server); tests that need one patch it back.
_llm._adc_project = lambda: None


@pytest.fixture(autouse=True)
def _no_leftover_serp_client():
    """A test that makes the shared SerpAPI client (``serp_flights._client``)
    must not hand it to later tests: it is bound to that test's event loop,
    and closing it from another loop (the app's shutdown) fails. Dropped
    after each test, so results never depend on test order."""
    from app.services import serp_flights

    before = serp_flights._client
    yield
    serp_flights._client = before


class _NoModelNetwork:
    """Stands in for every real model client: tests never reach Vertex AI
    or Anthropic (no credentials, no spend). Tests that need replies patch
    ``app.core.llm.generate`` / ``stream`` or the client getters."""

    def __getattr__(self, name):
        raise RuntimeError("model network calls are disabled in tests")


@pytest.fixture(autouse=True)
def _no_model_network(monkeypatch):
    from app.core import llm

    monkeypatch.setattr(llm, "_gemini_client", lambda: _NoModelNetwork())
    monkeypatch.setattr(llm, "_anthropic_client", lambda: _NoModelNetwork())
    monkeypatch.setattr(llm, "_anthropic_sync", _NoModelNetwork())
    llm.reset_spend_cap()
    llm._resolved = None
    yield
    llm.reset_spend_cap()
    llm._resolved = None


@pytest.fixture(scope="session", autouse=True)
def place_data():
    """Seed the place data once, before any test: lookups (airports, static
    tables' country fallback) read it, whatever the test order."""
    from app.db.seed_airports import seed

    seed()


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(client):
    r = client.post(
        "/api/auth/login", json={"username": "admin", "password": "test-admin-pw!"}
    )
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session", autouse=True)
def trip_tables(place_data):
    """Create the Phase 2 trip tables once, whatever the test order (the app
    lifespan creates them in production)."""
    from app.db import plans_db
    from app.db.trips_schema import create_trip_tables

    plans_db.create_plans_table()
    create_trip_tables()
    from app.db.shares_db import create_shares_table

    create_shares_table()
