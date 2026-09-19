"""The passwords must never reach a subprocess argument list.

``ps`` is readable by anything else in the container, so a password in argv is
a password leaked for as long as qpdf runs. Sampling ``ps`` in a test races
with a process that lives for milliseconds, so instead this captures the exact
argv the services build and asserts on it directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services import protect as protect_service
from app.services import unlock as unlock_service
from app.services.runner import ToolResult
from tests.conftest import requires_qpdf, upload

SECRET = "correct horse battery staple"


@pytest.fixture
def captured_argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record every command the services spawn, and let the real qpdf run it."""
    seen: list[list[str]] = []
    real_run = protect_service.run

    async def spy(command: Sequence[str], **kwargs: Any) -> ToolResult:
        seen.append([str(part) for part in command])
        return await real_run(command, **kwargs)

    monkeypatch.setattr(protect_service, "run", spy)
    monkeypatch.setattr(unlock_service, "run", spy)
    return seen


@requires_qpdf
def test_protect_keeps_the_password_out_of_argv(
    client: TestClient, text_pdf: bytes, captured_argv: list[list[str]]
) -> None:
    response = client.post(
        "/protect", files=[upload("a.pdf", text_pdf)], data={"password": SECRET}
    )
    assert response.status_code == 200

    assert captured_argv, "protect did not spawn qpdf"
    for command in captured_argv:
        assert SECRET not in " ".join(command)
    # It goes through an @argument-file instead, because qpdf 11.3 has no
    # --user-password/--owner-password options to hide it behind.
    assert captured_argv[0][0] == "qpdf"
    assert captured_argv[0][1].startswith("@")


@requires_qpdf
def test_unlock_keeps_the_password_out_of_argv(
    client: TestClient, encrypted_pdf: bytes, captured_argv: list[list[str]]
) -> None:
    response = client.post(
        "/unlock", files=[upload("a.pdf", encrypted_pdf)], data={"password": "hunter2"}
    )
    assert response.status_code == 200

    assert captured_argv, "unlock did not spawn qpdf"
    joined = " ".join(captured_argv[0])
    assert "hunter2" not in joined
    assert "--password-file=" in joined


@requires_qpdf
def test_the_secret_file_is_not_world_readable(
    client: TestClient, text_pdf: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    modes: list[int] = []
    real_write = protect_service.argument_file

    def spy(directory: Path, arguments: list[str], name: str = "args") -> Path:
        path = real_write(directory, arguments, name)
        modes.append(path.stat().st_mode & 0o777)
        return path

    monkeypatch.setattr(protect_service, "argument_file", spy)
    client.post("/protect", files=[upload("a.pdf", text_pdf)], data={"password": SECRET})

    assert modes == [0o600]
