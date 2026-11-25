"""`POST /api/uploads` 라우터 — 가짜 writer·실제 LocalInboxWriter로 multipart 경로를 확인한다."""

import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.unit.upload_fakes import MP3, WAV, FakeWriter

_URL = "/api/uploads"
_NAME = "20261124_101500_김상담_A산업.mp3"


def _api(build_app: Callable[..., FastAPI], writer: Any, **overrides: Any) -> TestClient:
    app = build_app(**overrides)
    app.state.inbox_writer = writer
    return TestClient(app)


def _files(*items: tuple[str, bytes]) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (name, data, "application/octet-stream")) for name, data in items]


def test_upload_returns_202_with_names(build_app: Callable[..., FastAPI]) -> None:
    writer = FakeWriter()

    response = _api(build_app, writer).post(_URL, files=_files((_NAME, MP3), ("b.WAV", WAV)))

    assert response.status_code == 202
    assert response.json() == {"items": [{"name": _NAME}, {"name": "b.wav"}]}
    assert writer.written == [(_NAME, MP3, "audio/mpeg"), ("b.wav", WAV, "audio/wav")]
    assert response.headers["X-Request-Id"]


def test_client_content_type_is_ignored(build_app: Callable[..., FastAPI]) -> None:
    writer = FakeWriter()

    response = _api(build_app, writer).post(_URL, files=[("files", ("a.mp3", MP3, "text/plain"))])

    assert response.status_code == 202
    assert writer.written[0][2] == "audio/mpeg"


def test_nfd_and_path_names_are_normalized(build_app: Callable[..., FastAPI]) -> None:
    writer = FakeWriter()
    nfd = "../" + unicodedata.normalize("NFD", _NAME)

    response = _api(build_app, writer).post(_URL, files=_files((nfd, MP3)))

    assert response.json() == {"items": [{"name": _NAME}]}


def test_disabled_backend_is_503(build_app: Callable[..., FastAPI]) -> None:
    response = TestClient(build_app()).post(_URL, files=_files(("a.txt", b"x")))

    assert response.status_code == 503
    assert response.json() == {
        "code": "INBOX_UNAVAILABLE",
        "message": "업로드 저장소를 사용할 수 없습니다.",
        "detail": None,
    }


def test_write_failure_is_503(build_app: Callable[..., FastAPI]) -> None:
    response = _api(build_app, FakeWriter(fail_at=0)).post(_URL, files=_files(("a.mp3", MP3)))

    assert response.status_code == 503
    assert response.json()["detail"] is None
    assert "http_503" not in response.text


def test_unsupported_media_is_415(build_app: Callable[..., FastAPI]) -> None:
    writer = FakeWriter()

    response = _api(build_app, writer).post(_URL, files=_files(("a.mp3", WAV)))

    assert response.status_code == 415
    assert response.json() == {
        "code": "UNSUPPORTED_MEDIA",
        "message": "허용되지 않은 파일 형식입니다.",
        "detail": {"index": 0},
    }
    assert writer.calls == 0


def test_bad_filename_is_422_without_name(build_app: Callable[..., FastAPI]) -> None:
    response = _api(build_app, FakeWriter()).post(_URL, files=_files(("김상담?.mp3", MP3)))

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["errors"][0]["loc"] == ["body", "files", 0]
    assert "김상담" not in response.text


def test_too_many_files_is_422(build_app: Callable[..., FastAPI]) -> None:
    files = _files(*((f"{i}.mp3", MP3) for i in range(11)))

    response = _api(build_app, FakeWriter()).post(_URL, files=files)

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["type"] == "too_many_files"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"data": {"note": "x"}},  # files 필드 없음 (multipart, 텍스트만)
        {"files": [("file", ("a.mp3", MP3, "audio/mpeg"))]},  # 다른 필드 이름
        {"files": [("files", ("", b"", "application/octet-stream"))]},  # 파일 미선택
    ],
)
def test_missing_files_is_422(build_app: Callable[..., FastAPI], kwargs: dict[str, Any]) -> None:
    response = _api(build_app, FakeWriter()).post(_URL, **kwargs)

    assert response.status_code == 422
    # 필드 없음: ["body", "files"] missing / 빈 파일명(httpx는 텍스트 필드로 보냄): [.., 0]
    assert response.json()["detail"]["errors"][0]["loc"][:2] == ["body", "files"]


def test_broken_multipart_is_400(build_app: Callable[..., FastAPI]) -> None:
    response = _api(build_app, FakeWriter()).post(
        _URL, content=b"garbage", headers={"Content-Type": "multipart/form-data"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"


def test_too_large_request_is_413(build_app: Callable[..., FastAPI]) -> None:
    writer = FakeWriter()
    big = MP3 + b"\x00" * (1024 * 1024)

    response = _api(build_app, writer, max_upload_mb=1).post(_URL, files=_files(("a.mp3", big)))

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert writer.calls == 0


# ---------------------------------------------------------------- 실제 LocalInboxWriter


def _local_api(build_app: Callable[..., FastAPI], root: Path) -> TestClient:
    return TestClient(build_app(inbox_backend="local", inbox_local_path=root))


def test_local_backend_writes_nfc_name_and_bytes(
    build_app: Callable[..., FastAPI], tmp_path: Path
) -> None:
    nfd = unicodedata.normalize("NFD", _NAME)

    response = _local_api(build_app, tmp_path).post(_URL, files=_files((nfd, MP3)))

    assert response.status_code == 202
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {_NAME: MP3}


def test_local_backend_handles_spooled_large_file(
    build_app: Callable[..., FastAPI], tmp_path: Path
) -> None:
    big = WAV + bytes(range(256)) * 8192  # 2 MiB 넘음 → 디스크 임시 파일로 넘어감

    response = _local_api(build_app, tmp_path).post(_URL, files=_files(("big.wav", big)))

    assert response.status_code == 202
    assert (tmp_path / "big.wav").read_bytes() == big


def test_local_backend_same_name_twice_gets_suffix(
    build_app: Callable[..., FastAPI], tmp_path: Path
) -> None:
    client = _local_api(build_app, tmp_path)

    for _ in range(2):
        assert client.post(_URL, files=_files(("a.mp3", MP3))).status_code == 202

    assert sorted(p.name for p in tmp_path.iterdir()) == ["a (1).mp3", "a.mp3"]


def test_allowed_extensions_setting_is_applied(build_app: Callable[..., FastAPI]) -> None:
    client = _api(build_app, FakeWriter(), allowed_extensions=["wav"])

    assert client.post(_URL, files=_files(("a.mp3", MP3))).status_code == 415
    assert client.post(_URL, files=_files(("a.wav", WAV))).status_code == 202


# ---------------------------------------------------------------- OpenAPI


def test_openapi_upload_files(build_app: Callable[..., FastAPI]) -> None:
    spec = build_app().openapi()
    operation = spec["paths"][_URL]["post"]
    body_ref = operation["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
    body = spec["components"]["schemas"][body_ref.rsplit("/", 1)[-1]]

    assert operation["operationId"] == "upload_files"
    assert operation["tags"] == ["uploads"]
    assert set(operation["responses"]) == {"202", "400", "413", "415", "422", "500", "503"}
    assert body["required"] == ["files"]
    assert body["properties"]["files"]["type"] == "array"
    ok = operation["responses"]["202"]["content"]["application/json"]["schema"]["$ref"]
    assert ok.endswith("/UploadResponse")
