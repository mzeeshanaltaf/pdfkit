"""HTTP routers. Each one parses a multipart form, calls a service, and returns
the result through ``app.services.responses.file_response``.

Grouped by what they need rather than by what they do, because ``app.main``
attaches the per-request dependencies at include time — so an endpoint added to
one of these routers later cannot be added without them.

``PROCESSING_ROUTERS`` do real work: rate limit, token, progress publisher.
``STREAM_ROUTERS`` is the SSE endpoint: same token, its own much looser limit,
and no publisher of its own (it is the consumer).
``OPEN_ROUTERS`` is the short list of things that cannot present a token —
``GET /ocr/languages``, fetched by the language picker on page load before any
run. ``/health`` is defined on the app itself, for the same reason.
"""

from app.routers import compress, convert, images, ocr, progress, protect, unlock

PROCESSING_ROUTERS = (
    compress.router,
    protect.router,
    unlock.router,
    ocr.router,
    images.router,
    convert.router,
)

STREAM_ROUTERS = (progress.router,)

OPEN_ROUTERS = (ocr.languages_router,)

__all__ = ["OPEN_ROUTERS", "PROCESSING_ROUTERS", "STREAM_ROUTERS"]
