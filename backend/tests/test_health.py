def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_has_request_id(client):
    r = client.get("/health")
    assert "x-request-id" in r.headers
    assert len(r.headers["x-request-id"]) == 36  # UUID


def test_health_propagates_request_id(client):
    r = client.get("/health", headers={"X-Request-ID": "my-custom-id"})
    assert r.headers.get("x-request-id") == "my-custom-id"
