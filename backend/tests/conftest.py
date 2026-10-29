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

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


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
