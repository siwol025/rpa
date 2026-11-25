"""음성 재생 라우터 단위 테스트: 실제 LocalStorage(tmp_path) + 가짜 세션(get_db 오버라이드)."""

import io
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_audio_storage, get_db
from app.core.errors import ErrorCode, error_status
from app.core.logging import configure_logging
from app.infra.storage import ByteRange, LocalStorage
from tests.audio_fakes import DATA, SIZE, FakeSession, ReadRecorder

_ABSENT_KEY = "00000000-0000-4000-8000-000000000000.wav"


@dataclass
class Env:
    app: FastAPI
    client: TestClient
    storage: LocalStorage
    events: list[str] = field(default_factory=list)
    key: str | None = None  # 가짜 세션이 돌려줄 object_key (None = 없는 건)

    def save(self, data: bytes = DATA, extension: str = ".wav") -> str:
        self.key = self.storage.save(io.BytesIO(data), extension=extension)
        return self.key


@pytest.fixture
def env(build_app: Callable[..., FastAPI], tmp_path: Path) -> Iterator[Env]:
    root = tmp_path / "audio"
    app = build_app(audio_storage_root=root)
    env = Env(app, TestClient(app), LocalStorage(root))

    def fake_db() -> Iterator[FakeSession]:
        env.events.append("db_open")
        try:
            yield FakeSession(env.key, env.events)
        finally:
            env.events.append("db_close")

    app.dependency_overrides[get_db] = fake_db
    with env.client:
        yield env


def _url(call_id: int | str = 7) -> str:
    return f"/api/calls/{call_id}/audio"


def _log_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


# ---------------------------------------------------------------- 200 / 206


def test_full_audio_without_range(env: Env) -> None:
    env.save()

    response = env.client.get(_url())

    assert response.status_code == 200
    assert response.content == DATA
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["content-length"] == str(SIZE)
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"] == 'inline; filename="call-7.wav"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-range" not in response.headers
    assert response.headers["x-request-id"]


@pytest.mark.parametrize(
    ("header", "start", "end"),
    [
        ("bytes=0-", 0, SIZE - 1),  # Chrome·Firefox 재생 시작
        ("bytes=0-1", 0, 1),  # Safari 확인 요청
        ("bytes=100-199", 100, 199),
        ("bytes=-10", SIZE - 10, SIZE - 1),
        ("bytes=5000-", 5000, SIZE - 1),  # 탐색(seek)
        ("bytes=0-99999999", 0, SIZE - 1),
    ],
)
def test_single_range_is_partial_content(env: Env, header: str, start: int, end: int) -> None:
    env.save()

    response = env.client.get(_url(), headers={"Range": header})

    assert response.status_code == 206
    assert response.content == DATA[start : end + 1]
    assert response.headers["content-range"] == f"bytes {start}-{end}/{SIZE}"
    assert response.headers["content-length"] == str(end - start + 1)
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("header", ["bytes=5-2", "bytes=abc", "items=0-1", "bytes=0-1,5-6"])
def test_invalid_unknown_or_multi_range_is_full(env: Env, header: str) -> None:
    env.save()

    response = env.client.get(_url(), headers={"Range": header})

    assert response.status_code == 200
    assert response.content == DATA
    assert "content-range" not in response.headers


def test_if_range_makes_range_ignored(env: Env) -> None:
    env.save()

    response = env.client.get(_url(), headers={"Range": "bytes=0-1", "If-Range": '"abc"'})

    assert response.status_code == 200
    assert response.content == DATA


def test_mp3_is_audio_mpeg(env: Env) -> None:
    env.save(extension=".mp3")

    response = env.client.get(_url())

    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["content-disposition"] == 'inline; filename="call-7.mp3"'


def test_large_file_is_streamed_in_chunks(env: Env) -> None:
    big = bytes(range(256)) * 1024  # 256 KiB = 64 KiB 청크 4개
    env.save(big)

    response = env.client.get(_url(), headers={"Range": "bytes=1-"})

    assert response.status_code == 206
    assert response.content == big[1:]


# ---------------------------------------------------------------- 에러


def test_unsatisfiable_range_is_416_with_content_range(env: Env) -> None:
    env.save()

    response = env.client.get(_url(), headers={"Range": f"bytes={SIZE}-"})

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{SIZE}"
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "code": "RANGE_NOT_SATISFIABLE",
        "message": "요청한 범위를 제공할 수 없습니다.",
        "detail": None,
    }


def test_range_not_satisfiable_code_is_416() -> None:
    assert error_status(ErrorCode.RANGE_NOT_SATISFIABLE) == 416


def test_no_record_is_404(env: Env) -> None:
    response = env.client.get(_url())

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_missing_file_is_404_without_key(env: Env) -> None:
    env.key = _ABSENT_KEY

    response = env.client.get(_url())

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert _ABSENT_KEY not in response.text


def test_corrupt_key_is_500_without_key(env: Env) -> None:
    env.key = "../secret.wav"

    response = env.client.get(_url())

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "secret" not in response.text


@pytest.mark.parametrize("call_id", [0, "abc", 2**63])
def test_invalid_id_is_422(env: Env, call_id: int | str) -> None:
    response = env.client.get(_url(call_id))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_head_is_not_allowed(env: Env) -> None:
    env.save()

    response = env.client.head(_url())

    assert response.status_code == 405


def test_object_key_is_not_exposed(env: Env) -> None:
    key = env.save()

    response = env.client.get(_url(), headers={"Range": "bytes=0-1"})

    assert key not in str(response.headers)
    assert key.encode() not in response.content


# ---------------------------------------------------------------- 로그


def test_access_logs(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    key = env.save()
    configure_logging("INFO")  # 핸들러를 capsys의 stdout에 다시 연결

    env.client.get(_url(), headers={"Range": "bytes=100-199", "X-Request-Id": "rid-audio"})

    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    (audio,) = [line for line in lines if line.get("event") == "audio_access"]
    assert audio["logger"] == "app.audio"
    assert audio["call_id"] == 7
    assert audio["request_id"] == "rid-audio"
    assert (audio["range_start"], audio["range_end"]) == (100, 199)
    assert (audio["status"], audio["bytes"]) == (206, 100)
    (access,) = [line for line in lines if line.get("logger") == "app.access"]
    assert (access["status"], access["call_id"]) == (206, 7)
    # Range 원문·키·클라이언트 주소는 남기지 않는다
    assert "bytes=100-199" not in out
    assert key not in out
    assert "testclient" not in out


def test_rejected_requests_do_not_log_audio_access(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.save()
    configure_logging("INFO")
    env.client.get(_url(), headers={"Range": f"bytes={SIZE}-"})  # 416
    env.key = None
    env.client.get(_url())  # 404

    events = [line.get("event") for line in _log_lines(capsys)]

    assert "audio_access" not in events
    assert events.count("request") == 2  # app.access는 상태와 무관하게 남는다


# ---------------------------------------------------------------- 세션 수명


def test_db_session_is_closed_before_streaming(env: Env) -> None:
    env.save(bytes(range(256)) * 1024)  # 청크 4개
    real = env.storage

    class RecordingStorage:
        def size(self, key: str) -> int:
            return real.size(key)

        def open(self, key: str, byte_range: ByteRange | None = None) -> BinaryIO:
            return cast(BinaryIO, ReadRecorder(real.open(key, byte_range), env.events))

    env.app.dependency_overrides[get_audio_storage] = RecordingStorage

    response = env.client.get(_url())

    assert response.status_code == 200
    assert env.events[:3] == ["db_open", "query", "db_close"]
    assert env.events[3:] and set(env.events[3:]) == {"read"}


# ---------------------------------------------------------------- OpenAPI


def test_openapi_get_call_audio(env: Env) -> None:
    operation = env.app.openapi()["paths"]["/api/calls/{call_id}/audio"]["get"]

    assert operation["operationId"] == "get_call_audio"
    assert operation["tags"] == ["calls"]
    assert set(operation["responses"]) == {"200", "206", "404", "416", "422", "500"}
    for status in ("200", "206"):
        assert set(operation["responses"][status]["content"]) == {"audio/wav", "audio/mpeg"}
    assert operation["responses"]["416"]["description"] == "RANGE_NOT_SATISFIABLE"
