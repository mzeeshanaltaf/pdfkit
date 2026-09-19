"""HTTP routers. Each one parses a multipart form, calls a service, and returns
the result through ``app.services.responses.file_response``."""

from app.routers import compress, convert, images, ocr, protect, unlock

ROUTERS = (
    compress.router,
    protect.router,
    unlock.router,
    ocr.router,
    images.router,
    convert.router,
)

__all__ = ["ROUTERS"]
