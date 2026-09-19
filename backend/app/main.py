"""FastAPI entrypoint: CORS, logging and the tool routers."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import APP_NAME, CORS_ORIGINS
from app.routers import ROUTERS

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

app = FastAPI(title=f"{APP_NAME} API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    # A cross-origin fetch() can only read headers listed here, and the UI needs
    # the download name and the before/after sizes.
    expose_headers=["Content-Disposition", "X-Original-Size", "X-Result-Size"],
)

for router in ROUTERS:
    app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
