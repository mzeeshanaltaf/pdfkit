"""Short-lived bearer tokens, minted by the Next server and verified here.

**This is a cost gate, not a security boundary.** It stops a script from using
`api.pdfkit.zeeshanai.cloud` as a free PDF service; it does not stop anyone who
copies a token out of devtools, and nothing short of user accounts would. This
app deliberately has no accounts, so the honest goal is "not trivially
scriptable by a third party", and that is all this achieves. Do not build
anything on top of it that assumes more.

The format is a compact HMAC rather than a JWT: no new dependency, no
algorithm-confusion bug class, and the whole verification is the function at the
bottom of this file.

    v1.<b64url(payload)>.<b64url(hmac_sha256(secret, "v1." + payload))>
    payload = {"exp": …, "nbf": …, "aud": "pdfkit-api", "jti": "<16 hex>"}

The token is checked at request *start* only, so a 120-second TTL is no problem
for a ten-minute OCR run that began inside it.

Not bound to the client's IP: mobile egress addresses change mid-session
(CGNAT, Wi-Fi to LTE), and Next and this service derive the address
independently, so a mismatch would be an unreproducible support problem for no
gain. Not bound to Origin either: CORS already enforces that for browsers, and
a non-browser caller sets whatever Origin it likes.

``jti`` is carried but not checked. A replay cache buys nothing against a
120-second window.

Everything reads ``config`` attributes **at call time**, never
``from app.config import API_TOKEN_SECRET`` — that would bind a copy at import
and make ``monkeypatch`` silently useless in the tests.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import logging
import secrets
import time
from hashlib import sha256

from app import config

logger = logging.getLogger(__name__)

VERSION = "v1"

# The distinct failures, as the `detail` the UI maps to a sentence.
AUTH_REQUIRED = "auth_required"
AUTH_EXPIRED = "auth_expired"
AUTH_INVALID = "auth_invalid"


class TokenError(Exception):
    """A token that will not do, carrying the code to report."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def enabled() -> bool:
    """False when no secret is configured, which leaves the API wide open.

    Deliberately not fatal: a backend that refuses to boot on a missing deploy
    variable is a worse outage than one that runs unauthenticated. It says so
    loudly at startup and on ``/health`` instead.
    """
    return bool(config.API_TOKEN_SECRET)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(secret: str, signing_input: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), sha256)
    return _b64(digest.digest())


def mint(secret: str | None = None, *, ttl: int | None = None) -> tuple[str, int]:
    """A fresh token and the epoch second it expires.

    Used by the tests and by nothing else in this service — production tokens
    are minted by the Next route, which implements the same three lines.
    """
    key = secret if secret is not None else config.API_TOKEN_SECRET
    now = int(time.time())
    expires = now + (ttl if ttl is not None else config.API_TOKEN_TTL_SECONDS)
    payload = {
        "exp": expires,
        "nbf": now - config.API_TOKEN_SKEW_SECONDS,
        "aud": config.API_TOKEN_AUDIENCE,
        "jti": secrets.token_hex(8),
    }
    encoded = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{VERSION}.{encoded}"
    return f"{signing_input}.{_sign(key, signing_input)}", expires


def bearer(header: str | None) -> str:
    """The token out of an ``Authorization`` header, or raise ``auth_required``."""
    if not header:
        raise TokenError(AUTH_REQUIRED)
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise TokenError(AUTH_REQUIRED)
    return value.strip()


def verify(token: str) -> None:
    """Raise :class:`TokenError` unless ``token`` is one we minted and still live.

    The order matters for the reported code: signature first, because an
    "expired" answer on a token we never signed would be telling a stranger
    something about our clock.
    """
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != VERSION:
        raise TokenError(AUTH_REQUIRED)

    signing_input = f"{parts[0]}.{parts[1]}"
    # The previous secret verifies but never mints, so rotating the shared
    # value does not invalidate the tokens already in flight.
    secrets_to_try = [config.API_TOKEN_SECRET, config.API_TOKEN_SECRET_PREVIOUS]
    if not any(
        hmac.compare_digest(_sign(secret, signing_input), parts[2])
        for secret in secrets_to_try
        if secret
    ):
        raise TokenError(AUTH_INVALID)

    try:
        payload = json.loads(_unb64(parts[1]))
    except (ValueError, binascii.Error) as error:
        raise TokenError(AUTH_INVALID) from error
    if not isinstance(payload, dict):
        raise TokenError(AUTH_INVALID)

    if payload.get("aud") != config.API_TOKEN_AUDIENCE:
        raise TokenError(AUTH_INVALID)

    now = time.time()
    try:
        expires = float(payload["exp"])
        not_before = float(payload["nbf"])
    except (KeyError, TypeError, ValueError) as error:
        raise TokenError(AUTH_INVALID) from error

    if now < not_before:
        # A clock that far out of step is not an expiry, it is a bad token.
        raise TokenError(AUTH_INVALID)
    if now >= expires:
        raise TokenError(AUTH_EXPIRED)
