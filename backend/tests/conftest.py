"""Shared fixtures for the test suite.

Env vars must be set at module level (before any app imports) so pydantic-settings
reads them during Settings() instantiation at collection time.
"""

import os
import tempfile

# ─── Set test env vars BEFORE any app imports ─────────────────────────────────
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="tp_test_")
os.environ.setdefault("DATA_DIR", _TEST_DATA_DIR)
os.environ["ADMIN_PASSWORD"] = "test-admin-pw!"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-32chars-long!!"
os.environ["LOG_FORMAT"] = "text"
os.environ["BACKUP_BUCKET"] = ""

import pytest
from fastapi.testclient import TestClient


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
