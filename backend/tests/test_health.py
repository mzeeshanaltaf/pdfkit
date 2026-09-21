"""/health is deliberately unauthenticated: Traefik and Coolify poll it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config
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


def test_health_reports_the_live_daytona_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    """The thresholds an operator would otherwise have to SSH in to read."""
    monkeypatch.setattr(config, "DAYTONA_ENABLED", True)
    monkeypatch.setattr(config, "DAYTONA_API_KEY", "secret-key")
    monkeypatch.setattr(config, "DAYTONA_SNAPSHOT", "pdfkit-toolchain-abc123")
    monkeypatch.setattr(config, "DAYTONA_OPERATIONS", ["ocr", "compress"])
    monkeypatch.setattr(config, "DAYTONA_MIN_FILES", 4)
    monkeypatch.setattr(config, "DAYTONA_MIN_BYTES", 1024)
    monkeypatch.setattr(config, "DAYTONA_MAX_SANDBOXES", 3)

    body = client.get("/health").json()

    # The real key must never come back, only whether one is set.
    assert body["daytona"] == {
        "enabled": True,
        "api_key": True,
        "snapshot": "pdfkit-toolchain-abc123",
        "operations": ["ocr", "compress"],
        "min_files": 4,
        "min_bytes": 1024,
        "max_sandboxes": 3,
    }


def test_health_daytona_api_key_is_never_the_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "DAYTONA_API_KEY", "")
    body = client.get("/health").json()
    assert body["daytona"]["api_key"] is False
