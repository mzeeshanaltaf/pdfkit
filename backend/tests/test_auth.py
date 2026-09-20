"""Token verification, and which routes are deliberately open.

A reminder of what these tests are protecting, because it is easy to read them
as more than they are: this is a cost gate, not a security boundary. See
``app.services.auth``.
"""

from __future__ import annotations

import base64
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import auth, ratelimit

from .conftest import TEST_SECRET, upload

OTHER_SECRET = "a-different-secret"


@pytest.fixture
def anon() -> TestClient:
    """A client that sends no Authorization header of its own."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _auth_on(monkeypatch) -> None:
    monkeypatch.setattr(config, "API_TOKEN_SECRET", TEST_SECRET)
    monkeypatch.setattr(config, "API_TOKEN_SECRET_PREVIOUS", "")
    ratelimit.reset()


def post(client: TestClient, text_pdf: bytes, token: str | None):
    """A request that gets past the door and then stops.

    An invalid ``level`` makes the endpoint 400 before it reaches Ghostscript,
    which is what lets these tests assert on the door alone — and run on a
    machine that has no Ghostscript.
    """
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return client.post(
        "/compress",
        files=[upload("one.pdf", text_pdf)],
        data={"level": "not-a-level"},
        headers=headers,
    )


def test_no_header_is_auth_required(anon: TestClient, text_pdf: bytes) -> None:
    response = post(anon, text_pdf, None)
    assert response.status_code == 401
    assert response.json()["detail"] == auth.AUTH_REQUIRED


def test_a_malformed_header_is_auth_required(anon: TestClient, text_pdf: bytes) -> None:
    response = anon.post(
        "/compress",
        files=[upload("one.pdf", text_pdf)],
        headers={"Authorization": "Basic abc"},
    )
    assert response.json()["detail"] == auth.AUTH_REQUIRED


def test_an_expired_token_says_so(anon: TestClient, text_pdf: bytes) -> None:
    token, _ = auth.mint(TEST_SECRET, ttl=-1)
    response = post(anon, text_pdf, token)
    assert response.status_code == 401
    assert response.json()["detail"] == auth.AUTH_EXPIRED


def test_a_token_from_another_secret_is_invalid(anon: TestClient, text_pdf: bytes) -> None:
    token, _ = auth.mint(OTHER_SECRET)
    response = post(anon, text_pdf, token)
    assert response.status_code == 401
    assert response.json()["detail"] == auth.AUTH_INVALID


def test_the_wrong_audience_is_invalid(monkeypatch) -> None:
    """A token minted for something else must not open this door."""
    monkeypatch.setattr(config, "API_TOKEN_AUDIENCE", "somewhere-else")
    token, _ = auth.mint(TEST_SECRET)
    monkeypatch.setattr(config, "API_TOKEN_AUDIENCE", "pdfkit-api")

    with pytest.raises(auth.TokenError) as raised:
        auth.verify(token)
    assert raised.value.code == auth.AUTH_INVALID


def test_a_tampered_payload_is_invalid() -> None:
    """The signature is checked before the claims, so this is not 'expired'."""
    token, _ = auth.mint(TEST_SECRET)
    version, payload, signature = token.split(".")
    decoded = json.loads(base64.urlsafe_b64decode(payload + "=="))
    decoded["exp"] = int(time.time()) + 86_400
    forged = (
        base64.urlsafe_b64encode(json.dumps(decoded).encode()).rstrip(b"=").decode()
    )

    with pytest.raises(auth.TokenError) as raised:
        auth.verify(f"{version}.{forged}.{signature}")
    assert raised.value.code == auth.AUTH_INVALID


def test_the_previous_secret_still_verifies(monkeypatch, anon: TestClient, text_pdf: bytes) -> None:
    """Rotation must not invalidate the tokens already in flight."""
    token, _ = auth.mint(OTHER_SECRET)
    monkeypatch.setattr(config, "API_TOKEN_SECRET_PREVIOUS", OTHER_SECRET)

    # 400 from the endpoint's own validation: past the door, which is the
    # whole assertion.
    assert post(anon, text_pdf, token).status_code == 400


def test_health_is_open(anon: TestClient) -> None:
    assert anon.get("/health").status_code == 200
    assert anon.get("/health").json()["auth"] == "on"


def test_the_language_list_is_open(anon: TestClient) -> None:
    """The picker fetches this on page load, before any token is minted."""
    response = anon.get("/ocr/languages")
    # 503 when tesseract is not installed, which is still not a 401.
    assert response.status_code in (200, 503)


def test_the_progress_stream_is_protected(anon: TestClient) -> None:
    """Only possible because the browser reads it with fetch, not EventSource."""
    assert anon.get(f"/progress/{'0' * 32}").status_code == 401


def test_no_secret_configured_lets_everything_through(monkeypatch) -> None:
    """A missing deploy variable degrades to open, loudly — it does not 500."""
    monkeypatch.setattr(config, "API_TOKEN_SECRET", "")
    assert not auth.enabled()
    assert TestClient(app).get("/health").json()["auth"] == "off"
