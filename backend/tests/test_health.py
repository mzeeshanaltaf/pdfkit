"""/health is deliberately unauthenticated: Traefik and Coolify poll it."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    # The counters exist so a registry or limiter leak is visible without a
    # debugger; a fresh process has nothing in either.
    assert body["jobs"] == 0
    assert body["streams"] == 0
    # The address the rate limiter is keying on. In production every visitor
    # showing the same Docker bridge address means uvicorn is not trusting the
    # proxy headers and the whole site shares one bucket.
    assert body["client"] == "testclient"


def test_health_needs_no_token() -> None:
    assert "auth" in client.get("/health").json()
