"""Per-IP sliding windows, and the client address they key on."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import ratelimit


@pytest.fixture(autouse=True)
def _clean() -> None:
    ratelimit.reset()


def test_the_window_allows_then_refuses() -> None:
    for _ in range(3):
        assert ratelimit.check("bucket", "1.2.3.4", 3, 60) is None
    retry_after = ratelimit.check("bucket", "1.2.3.4", 3, 60)
    assert retry_after is not None
    assert 0 < retry_after <= 60


def test_a_refused_hit_does_not_extend_the_window() -> None:
    """Otherwise a client hammering the door could never get back in."""
    ratelimit.check("bucket", "1.2.3.4", 1, 60)
    first = ratelimit.check("bucket", "1.2.3.4", 1, 60)
    second = ratelimit.check("bucket", "1.2.3.4", 1, 60)
    assert first is not None and second is not None
    assert second <= first


def test_addresses_are_independent() -> None:
    assert ratelimit.check("bucket", "1.1.1.1", 1, 60) is None
    assert ratelimit.check("bucket", "2.2.2.2", 1, 60) is None
    assert ratelimit.check("bucket", "1.1.1.1", 1, 60) is not None


def test_buckets_are_independent() -> None:
    assert ratelimit.check("one", "1.1.1.1", 1, 60) is None
    assert ratelimit.check("two", "1.1.1.1", 1, 60) is None


def test_the_store_is_lru_capped(monkeypatch) -> None:
    monkeypatch.setattr(config, "RATE_LIMIT_MAX_CLIENTS", 4)
    for index in range(20):
        ratelimit.check("bucket", f"10.0.0.{index}", 5, 60)
    assert ratelimit.tracked() <= 4


def test_a_forged_forwarded_for_header_cannot_change_the_key() -> None:
    """The whole XFF question is uvicorn's, and deliberately not ours.

    Its ProxyHeaders middleware walks the header right-to-left and returns the
    rightmost address that is not a trusted proxy, which cannot be spoofed by
    prepending entries. Parsing it a second time here — as the contact route
    used to, leftmost-first — is what would reintroduce the forgery.
    """
    client = TestClient(app)
    forged = client.get("/health", headers={"X-Forwarded-For": "9.9.9.9"})
    plain = client.get("/health")
    assert forged.json()["client"] == plain.json()["client"] == "testclient"


def test_over_the_limit_is_429_with_retry_after(monkeypatch, text_pdf: bytes) -> None:
    monkeypatch.setattr(config, "RATE_LIMIT_JOB_BURST", (2, 60))
    monkeypatch.setattr(config, "API_TOKEN_SECRET", "")  # not what is under test

    from .conftest import upload

    # An invalid level makes the endpoint 400 before it reaches Ghostscript;
    # the limiter runs before the endpoint either way.
    def attempt():
        return client.post(
            "/compress",
            files=[upload("one.pdf", text_pdf)],
            data={"level": "not-a-level"},
        )

    client = TestClient(app)
    for _ in range(2):
        assert attempt().status_code == 400

    response = attempt()
    assert response.status_code == 429
    assert response.json()["detail"] == ratelimit.RATE_LIMITED
    assert int(response.headers["Retry-After"]) >= 1


def test_health_is_never_limited(monkeypatch) -> None:
    """Traefik and Coolify poll this constantly and cannot mint a token."""
    monkeypatch.setattr(config, "RATE_LIMIT_COARSE", (1, 60))
    client = TestClient(app)
    for _ in range(5):
        assert client.get("/health").status_code == 200
