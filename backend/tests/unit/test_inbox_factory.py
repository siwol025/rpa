"""create_inbox_writer 분기와 앱 주입(app.state.inbox_writer, get_inbox_writer)."""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_inbox_writer
from app.core.config import Settings
from app.infra.inbox import InboxWriter, create_inbox_writer
from app.infra.inbox.drive import DriveInboxWriter
from app.infra.inbox.local import LocalInboxWriter


def test_disabled_gives_none() -> None:
    assert create_inbox_writer(Settings(_env_file=None, inbox_backend="disabled")) is None


def test_local_gives_local_writer_without_touching_disk(tmp_path: Path) -> None:
    root = tmp_path / "inbox"

    writer = create_inbox_writer(
        Settings(_env_file=None, inbox_backend="local", inbox_local_path=root)
    )

    assert isinstance(writer, LocalInboxWriter)
    assert not root.exists()


def test_drive_gives_drive_writer_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    writer = create_inbox_writer(
        Settings(_env_file=None, inbox_backend="drive", drive_inbox_folder_id="F1")
    )

    assert isinstance(writer, DriveInboxWriter)


def _app_with_probe(build_app: Callable[..., FastAPI], **overrides: Any) -> TestClient:
    app = build_app(**overrides)

    @app.get("/probe-inbox")
    def probe(writer: Annotated[InboxWriter | None, Depends(get_inbox_writer)]) -> dict[str, str]:
        return {"writer": type(writer).__name__}

    return TestClient(app)


def test_app_injects_none_by_default(build_app: Callable[..., FastAPI]) -> None:
    client = _app_with_probe(build_app)

    assert client.get("/probe-inbox").json() == {"writer": "NoneType"}


def test_app_injects_configured_writer(build_app: Callable[..., FastAPI], tmp_path: Path) -> None:
    client = _app_with_probe(build_app, inbox_backend="local", inbox_local_path=tmp_path)

    assert client.get("/probe-inbox").json() == {"writer": "LocalInboxWriter"}


def test_app_starts_with_drive_backend_without_credentials(
    build_app: Callable[..., FastAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    client = _app_with_probe(build_app, inbox_backend="drive", drive_inbox_folder_id="F1")

    assert client.get("/probe-inbox").json() == {"writer": "DriveInboxWriter"}
