"""음성 재생 통합 테스트: 실제 DB 조회(삭제 제외 조건) + 실제 LocalStorage(tmp_path)."""

import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_audio_storage, get_db
from app.core.config import Settings
from app.infra.storage import ByteRange, LocalStorage
from app.main import create_app
from tests.audio_fakes import DATA, SIZE, ReadRecorder
from tests.integration.factories import make_call

pytestmark = pytest.mark.integration


@dataclass
class AudioApi:
    client: TestClient
    storage: LocalStorage
    events: list[str] = field(default_factory=list)

    def save(self) -> str:
        return self.storage.save(io.BytesIO(DATA), extension=".wav")


@pytest.fixture
def audio_api(db_session: Session, tmp_path: Path) -> Iterator[AudioApi]:
    root = tmp_path / "audio"
    app = create_app(Settings(_env_file=None, audio_storage_root=root))
    storage = LocalStorage(root)
    env = AudioApi(TestClient(app), storage)

    def recording_db() -> Iterator[Session]:
        env.events.append("db_open")
        try:
            yield db_session
        finally:
            env.events.append("db_close")

    class RecordingStorage:
        def size(self, key: str) -> int:
            return storage.size(key)

        def open(self, key: str, byte_range: ByteRange | None = None) -> BinaryIO:
            return cast(BinaryIO, ReadRecorder(storage.open(key, byte_range), env.events))

    app.dependency_overrides[get_db] = recording_db
    app.dependency_overrides[get_audio_storage] = RecordingStorage
    with env.client:
        yield env


def test_partial_content_end_to_end(audio_api: AudioApi, db_session: Session) -> None:
    call = make_call(db_session, object_key=audio_api.save(), status="STORED")

    response = audio_api.client.get(f"/api/calls/{call.id}/audio", headers={"Range": "bytes=100-"})

    assert response.status_code == 206
    assert response.content == DATA[100:]
    assert response.headers["content-range"] == f"bytes 100-{SIZE - 1}/{SIZE}"
    assert response.headers["content-type"] == "audio/wav"


def test_session_closed_before_first_read(audio_api: AudioApi, db_session: Session) -> None:
    call = make_call(db_session, object_key=audio_api.save())

    response = audio_api.client.get(f"/api/calls/{call.id}/audio")

    assert response.status_code == 200
    assert audio_api.events[:2] == ["db_open", "db_close"]
    assert audio_api.events[2:] and set(audio_api.events[2:]) == {"read"}


@pytest.mark.parametrize("status", ["REGISTERED", "FAILED", "RETRY_REQUESTED"])
def test_any_status_is_playable(audio_api: AudioApi, db_session: Session, status: str) -> None:
    call = make_call(db_session, object_key=audio_api.save(), status=status)

    response = audio_api.client.get(f"/api/calls/{call.id}/audio")

    assert response.status_code == 200
    assert response.content == DATA


def test_soft_deleted_call_is_404(audio_api: AudioApi, db_session: Session) -> None:
    call = make_call(
        db_session, object_key=audio_api.save(), deleted_at=datetime(2026, 11, 24, tzinfo=UTC)
    )

    response = audio_api.client.get(f"/api/calls/{call.id}/audio")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_unknown_call_is_404(audio_api: AudioApi, db_session: Session) -> None:
    call = make_call(db_session, object_key=audio_api.save())

    response = audio_api.client.get(f"/api/calls/{call.id + 1000}/audio")

    assert response.status_code == 404
