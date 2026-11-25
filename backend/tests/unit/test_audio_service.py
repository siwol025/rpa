import io
import json
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.http_range import RangeNotSatisfiableError
from app.core.logging import configure_logging
from app.infra.storage import InvalidKeyError, LocalStorage
from app.services.audio_service import AudioService
from tests.audio_fakes import DATA, SIZE, FakeSession

MISSING_KEY = "00000000-0000-4000-8000-000000000000.wav"


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "audio")


def _service(storage: LocalStorage, key: str | None) -> AudioService:
    return AudioService(cast(Session, FakeSession(key)), storage)


def _logs(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_full_audio_without_range(storage: LocalStorage) -> None:
    key = storage.save(io.BytesIO(DATA), extension=".wav")

    audio = _service(storage, key).open_audio(7, None)

    with audio.stream:
        assert audio.stream.read() == DATA
    assert (audio.media_type, audio.extension) == ("audio/wav", ".wav")
    assert (audio.size, audio.byte_range, audio.length) == (SIZE, None, SIZE)


def test_range_opens_only_that_part(storage: LocalStorage) -> None:
    key = storage.save(io.BytesIO(DATA), extension=".wav")

    audio = _service(storage, key).open_audio(7, "bytes=100-199")

    with audio.stream:
        assert audio.stream.read() == DATA[100:200]
    assert (audio.byte_range, audio.length) == ((100, 199), 100)


def test_mp3_key_is_audio_mpeg(storage: LocalStorage) -> None:
    key = storage.save(io.BytesIO(DATA), extension=".mp3")

    audio = _service(storage, key).open_audio(7, None)
    audio.stream.close()

    assert (audio.media_type, audio.extension) == ("audio/mpeg", ".mp3")


def test_no_record_is_not_found(storage: LocalStorage) -> None:
    with pytest.raises(AppError) as exc_info:
        _service(storage, None).open_audio(7, None)

    assert exc_info.value.code == ErrorCode.NOT_FOUND


def test_missing_file_is_not_found_and_logs_without_key(
    storage: LocalStorage, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO")

    with pytest.raises(AppError) as exc_info:
        _service(storage, MISSING_KEY).open_audio(7, None)

    assert exc_info.value.code == ErrorCode.NOT_FOUND
    assert exc_info.value.__suppress_context__  # from None: 키가 든 원인 예외를 끊는다
    (log,) = [line for line in _logs(capsys) if line["event"] == "audio_missing"]
    assert (log["logger"], log["level"], log["call_id"]) == ("app.audio", "warning", 7)
    assert MISSING_KEY not in json.dumps(log)


def test_corrupt_key_propagates(storage: LocalStorage) -> None:
    with pytest.raises(InvalidKeyError):
        _service(storage, "audio/1.wav").open_audio(7, None)


def test_unsatisfiable_range_raises_with_size(storage: LocalStorage) -> None:
    key = storage.save(io.BytesIO(DATA), extension=".wav")

    with pytest.raises(RangeNotSatisfiableError) as exc_info:
        _service(storage, key).open_audio(7, f"bytes={SIZE}-")

    assert exc_info.value.size == SIZE


def test_invalid_range_is_full(storage: LocalStorage) -> None:
    key = storage.save(io.BytesIO(DATA), extension=".wav")

    audio = _service(storage, key).open_audio(7, "bytes=5-2")
    audio.stream.close()

    assert audio.byte_range is None


@pytest.mark.parametrize(
    ("header", "start", "end", "status", "sent"),
    [(None, None, None, 200, SIZE), ("bytes=-10", SIZE - 10, SIZE - 1, 206, 10)],
)
def test_access_log(
    storage: LocalStorage,
    capsys: pytest.CaptureFixture[str],
    header: str | None,
    start: int | None,
    end: int | None,
    status: int,
    sent: int,
) -> None:
    configure_logging("INFO")
    key = storage.save(io.BytesIO(DATA), extension=".wav")

    _service(storage, key).open_audio(7, header).stream.close()

    (log,) = [line for line in _logs(capsys) if line["event"] == "audio_access"]
    assert log["logger"] == "app.audio"
    assert log["level"] == "info"
    assert log["call_id"] == 7
    assert (log["range_start"], log["range_end"]) == (start, end)
    assert (log["status"], log["bytes"]) == (status, sent)
    assert key not in json.dumps(log)
