"""UploadService — 가짜 InboxWriter로 검증 순서·업로드·실패 변환을 확인한다."""

import io
from typing import Any

import pytest

from app.core.config import AudioExtension
from app.core.errors import AppError, ErrorCode
from app.core.logging import configure_logging
from app.services.upload_service import MAX_FILES_PER_REQUEST, IncomingFile, UploadService
from tests.unit.upload_fakes import MP3, WAV, FakeWriter

_NAME = "20261124_101500_김상담_A산업.mp3"


def _service(
    writer: FakeWriter | None, allowed: tuple[AudioExtension, ...] = ("wav", "mp3")
) -> UploadService:
    return UploadService(writer, allowed)


def _file(name: str | None, data: bytes) -> IncomingFile:
    return IncomingFile(name, io.BytesIO(data))


def _raises(code: ErrorCode, fn: Any, *args: Any) -> AppError:
    with pytest.raises(AppError) as info:
        fn(*args)
    assert info.value.code == code
    return info.value


def test_disabled_writer_is_503_before_validation() -> None:
    error = _raises(ErrorCode.INBOX_UNAVAILABLE, _service(None).upload, [_file("a.txt", b"x")])

    assert error.detail is None


def test_uploads_single_file_with_canonical_mime() -> None:
    writer = FakeWriter()

    response = _service(writer).upload([_file(_NAME, MP3)])

    assert response.model_dump() == {"items": [{"name": _NAME}]}
    assert writer.written == [(_NAME, MP3, "audio/mpeg")]


def test_uploads_multiple_files_in_order() -> None:
    writer = FakeWriter()

    response = _service(writer).upload([_file("b.wav", WAV), _file("a.mp3", MP3)])

    assert [item.name for item in response.items] == ["b.wav", "a.mp3"]
    assert writer.written == [("b.wav", WAV, "audio/wav"), ("a.mp3", MP3, "audio/mpeg")]


def test_upper_case_extension_is_saved_lower_case() -> None:
    writer = FakeWriter()

    response = _service(writer).upload([_file("REC.WAV", WAV)])

    assert response.items[0].name == "REC.wav"
    assert writer.written[0][0] == "REC.wav"


def test_writes_whole_stream_even_after_reading_head() -> None:
    writer = FakeWriter()
    stream = io.BytesIO(MP3)
    stream.read(5)

    _service(writer).upload([IncomingFile("a.mp3", stream)])

    assert writer.written[0][1] == MP3
    assert writer.positions == [0]


def test_too_many_files_is_422() -> None:
    writer = FakeWriter()
    files = [_file(f"{i}.mp3", MP3) for i in range(MAX_FILES_PER_REQUEST + 1)]

    error = _raises(ErrorCode.VALIDATION_ERROR, _service(writer).upload, files)

    assert error.detail == {
        "errors": [
            {
                "loc": ["body", "files"],
                "msg": "파일은 한 번에 최대 10개까지 올릴 수 있습니다",
                "type": "too_many_files",
            }
        ]
    }
    assert writer.calls == 0


def test_max_files_is_allowed() -> None:
    writer = FakeWriter()
    files = [_file(f"{i}.mp3", MP3) for i in range(MAX_FILES_PER_REQUEST)]

    _service(writer).upload(files)

    assert writer.calls == MAX_FILES_PER_REQUEST


@pytest.mark.parametrize("name", [None, "", "a:b.mp3", "a.mp3.", ".mp3"])
def test_bad_filename_is_422_with_index_and_no_name(name: str | None) -> None:
    writer = FakeWriter()

    error = _raises(
        ErrorCode.VALIDATION_ERROR,
        _service(writer).upload,
        [_file("ok.mp3", MP3), _file(name, MP3)],
    )

    assert error.detail == {
        "errors": [
            {
                "loc": ["body", "files", 1],
                "msg": "사용할 수 없는 파일명입니다",
                "type": "filename_invalid",
            }
        ]
    }
    assert writer.calls == 0  # 앞 파일도 올리지 않음


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("a", MP3),  # 확장자 없음
        ("a.m4a", b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 8),  # 허용 목록 밖
        ("a.txt", MP3),
        ("a.mp3", b""),  # 빈 파일
        ("a.mp3", WAV),  # 확장자와 내용 불일치
        ("a.wav", MP3),
        ("a.mp3", b"\xff\xf1\x50\x80" + b"\x00" * 8),  # AAC
        ("a.wav", b"hello world, not audio"),
    ],
)
def test_unsupported_media_is_415_with_index(name: str, data: bytes) -> None:
    writer = FakeWriter()

    error = _raises(
        ErrorCode.UNSUPPORTED_MEDIA,
        _service(writer).upload,
        [_file("ok.wav", WAV), _file(name, data)],
    )

    assert error.detail == {"index": 1}
    assert writer.calls == 0


def test_allowed_extensions_setting_limits_formats() -> None:
    writer = FakeWriter()

    _raises(ErrorCode.UNSUPPORTED_MEDIA, _service(writer, ("wav",)).upload, [_file("a.mp3", MP3)])
    _service(writer, ("wav",)).upload([_file("a.wav", WAV)])

    assert [w[0] for w in writer.written] == ["a.wav"]


def test_write_failure_stops_and_is_503_without_reason() -> None:
    writer = FakeWriter(fail_at=1)
    files = [_file("a.mp3", MP3), _file("b.mp3", MP3), _file("c.mp3", MP3)]

    error = _raises(ErrorCode.INBOX_UNAVAILABLE, _service(writer).upload, files)

    assert error.detail is None
    assert "http_503" not in error.message
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    assert writer.calls == 2  # 실패한 b 이후(c)는 시도하지 않음
    assert [w[0] for w in writer.written] == ["a.mp3"]  # 앞서 올린 파일은 그대로


def test_logs_have_no_file_name_or_cause(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")  # 핸들러를 capsys의 stdout에 다시 단다
    name = "leak-check_agent_client.mp3"  # JSON 로그는 한글을 \uXXXX로 내므로 ASCII 이름으로 확인

    _service(FakeWriter()).upload([_file(name, MP3)])
    with pytest.raises(AppError):
        _service(FakeWriter(fail_at=0)).upload([_file(name, MP3)])

    out = capsys.readouterr().out
    assert "upload_accepted" in out
    assert "upload_aborted" in out
    assert "http_503" in out  # reason은 남긴다
    assert "leak-check" not in out
    assert "secret-key-path" not in out
    assert "Traceback" not in out
