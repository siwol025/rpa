"""DriveInboxWriter — HttpMockSequence로 Drive API 응답을 흉내 낸다 (네트워크·자격 증명 없음)."""

import io
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httplib2
import pytest
from google.auth.credentials import AnonymousCredentials
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from googleapiclient.http import HttpMockSequence

from app.core.logging import configure_logging
from app.infra.inbox import InboxUnavailableError
from app.infra.inbox.drive import DRIVE_SCOPES, DriveInboxWriter

_FOLDER_ID = "FOLDER123"
_SESSION = {"status": "200", "location": "https://upload.example/session-1"}
_CREATED = ({"status": "200"}, json.dumps({"id": "FILE123"}))
_NOT_RECEIVED = ({"status": "308"}, "")  # 상태 조회 응답: 받은 바이트 없음 (range 헤더 없음)
_FOLDER_OK = {
    "id": _FOLDER_ID,
    "mimeType": "application/vnd.google-apps.folder",
    "trashed": False,
    "capabilities": {"canAddChildren": True},
}


def _error(status: int, reason: str) -> tuple[dict[str, str], str]:
    body = {"error": {"code": status, "message": "m", "errors": [{"reason": reason}]}}
    return {"status": str(status)}, json.dumps(body)


_Response = tuple[dict[str, str], str] | Exception


class _RecordingHttp(HttpMockSequence):  # type: ignore[misc]
    """실제 소켓처럼 요청 시점에 본문 스트림을 읽어 기록한다. 응답 자리에 예외를 두면 던진다."""

    def request(
        self,
        uri: str,
        method: str = "GET",
        body: Any = None,
        headers: Any = None,
        redirections: int = 1,
        connection_type: Any = None,
    ) -> tuple[httplib2.Response, bytes]:
        data = body.read() if hasattr(body, "read") else body
        self.request_sequence.append((uri, method, data, headers))
        item = self._iterable.pop(0)
        if isinstance(item, Exception):
            raise item
        resp, content = item
        return httplib2.Response(resp), content.encode("utf-8")


class _Factory:
    """http_factory 대역. 넘겨받은 타임아웃을 기록하고 준비한 _RecordingHttp를 돌려준다."""

    def __init__(self, responses: list[_Response]) -> None:
        self.http = _RecordingHttp(responses)
        self.timeouts: list[float] = []

    def __call__(self, timeout: float) -> Any:
        self.timeouts.append(timeout)
        return self.http

    @property
    def requests(self) -> list[tuple[str, str, Any, Any]]:
        return list(self.http.request_sequence)


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr("app.infra.inbox.drive.time.sleep", slept.append)
    return slept


def _writer(factory: _Factory) -> DriveInboxWriter:
    return DriveInboxWriter(_FOLDER_ID, http_factory=factory)


def _write(writer: DriveInboxWriter, data: bytes = b"RIFF....") -> str:
    return writer.write("20261124_101500_김상담_A산업.wav", io.BytesIO(data), "audio/wav")


# ---------------------------------------------------------------- write


def test_write_uses_resumable_upload_to_shared_drive_folder() -> None:
    factory = _Factory([(_SESSION, ""), _CREATED])

    file_id = _write(_writer(factory))

    assert file_id == "FILE123"
    (start_uri, start_method, start_body, _), (put_uri, put_method, put_body, _) = factory.requests
    query = parse_qs(urlsplit(start_uri).query)
    assert start_method == "POST"
    assert urlsplit(start_uri).path == "/upload/drive/v3/files"
    assert query["uploadType"] == ["resumable"]
    assert query["supportsAllDrives"] == ["true"]
    assert query["fields"] == ["id"]
    assert json.loads(start_body) == {
        "name": "20261124_101500_김상담_A산업.wav",
        "parents": [_FOLDER_ID],
        "properties": {"source": "web"},
    }
    assert (put_uri, put_method) == ("https://upload.example/session-1", "PUT")
    assert put_body == b"RIFF...."


def test_write_sends_content_type_of_media() -> None:
    factory = _Factory([(_SESSION, ""), _CREATED])

    _write(_writer(factory))

    start_headers = factory.requests[0][3]
    assert start_headers["X-Upload-Content-Type"] == "audio/wav"


def test_write_reads_stream_from_start() -> None:
    factory = _Factory([(_SESSION, ""), _CREATED])
    stream = io.BytesIO(b"RIFF....")
    stream.read(4)  # 호출자가 매직 바이트를 읽고 되감지 않은 경우

    _writer(factory).write("a.wav", stream, "audio/wav")

    assert factory.requests[1][2] == b"RIFF...."


def test_write_uses_upload_timeout() -> None:
    factory = _Factory([(_SESSION, ""), _CREATED])

    _write(_writer(factory))

    assert factory.timeouts == [30.0]


def _puts(factory: _Factory) -> list[tuple[Any, Any]]:
    return [(body, headers) for _, method, body, headers in factory.requests if method == "PUT"]


def test_write_retries_server_error_then_succeeds(_no_backoff_sleep: list[float]) -> None:
    factory = _Factory([(_SESSION, ""), ({"status": "503"}, ""), _NOT_RECEIVED, _CREATED])

    assert _write(_writer(factory)) == "FILE123"
    first, status_query, retried = _puts(factory)
    assert first[0] == b"RIFF...."
    assert status_query[1]["Content-Range"] == "bytes */8"  # 서버가 받은 위치를 먼저 묻는다
    assert retried[0] == b"RIFF...."  # 재전송 본문이 비지 않고 전체 바이트
    assert len(_no_backoff_sleep) == 1


def test_write_resends_after_network_error_during_put(_no_backoff_sleep: list[float]) -> None:
    factory = _Factory([(_SESSION, ""), ConnectionResetError(), _NOT_RECEIVED, _CREATED])

    assert _write(_writer(factory)) == "FILE123"
    _, status_query, retried = _puts(factory)
    assert status_query[1]["Content-Range"] == "bytes */8"
    assert retried[0] == b"RIFF...."
    assert len(_no_backoff_sleep) == 1


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (_error(403, "insufficientFilePermissions"), "http_403"),
        (_error(404, "notFound"), "http_404"),
    ],
)
def test_write_fails_immediately_on_non_retryable_put_error(
    error: tuple[dict[str, str], str], reason: str, _no_backoff_sleep: list[float]
) -> None:
    factory = _Factory([(_SESSION, ""), error])

    with pytest.raises(InboxUnavailableError) as exc_info:
        _write(_writer(factory))

    assert exc_info.value.reason == reason
    assert len(factory.requests) == 2
    assert _no_backoff_sleep == []


def test_write_gives_up_put_after_two_retries(_no_backoff_sleep: list[float]) -> None:
    unavailable = ({"status": "503"}, "")
    factory = _Factory(
        [(_SESSION, ""), unavailable, _NOT_RECEIVED, unavailable, _NOT_RECEIVED, unavailable]
    )

    with pytest.raises(InboxUnavailableError) as exc_info:
        _write(_writer(factory))

    assert exc_info.value.reason == "http_503"
    assert len(factory.requests) == 6
    assert len(_no_backoff_sleep) == 2


@pytest.mark.parametrize(
    "error",
    [_error(429, "rateLimitExceeded"), _error(403, "userRateLimitExceeded")],
    ids=["429", "403-rate-limit"],
)
def test_write_retries_rate_limit(error: tuple[dict[str, str], str]) -> None:
    factory = _Factory([error, (_SESSION, ""), _CREATED])

    assert _write(_writer(factory)) == "FILE123"


def test_write_gives_up_after_two_retries(_no_backoff_sleep: list[float]) -> None:
    factory = _Factory([({"status": "503"}, "")] * 3)

    with pytest.raises(InboxUnavailableError) as exc_info:
        _write(_writer(factory))

    assert exc_info.value.reason == "http_503"
    assert len(factory.requests) == 3
    assert len(_no_backoff_sleep) == 2


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (_error(404, "notFound"), "http_404"),
        (_error(403, "insufficientFilePermissions"), "http_403"),
        (_error(403, "storageQuotaExceeded"), "http_403"),
        (_error(400, "badRequest"), "http_400"),
    ],
)
def test_write_fails_immediately_on_non_retryable_error(
    error: tuple[dict[str, str], str], reason: str
) -> None:
    factory = _Factory([error])

    with pytest.raises(InboxUnavailableError) as exc_info:
        _write(_writer(factory))

    assert exc_info.value.reason == reason
    assert len(factory.requests) == 1


def test_write_failure_log_has_no_file_name_or_folder_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")  # 핸들러를 capsys의 stdout에 다시 단다
    factory = _Factory([_error(404, "notFound")])

    with pytest.raises(InboxUnavailableError):
        _write(_writer(factory))

    out = capsys.readouterr().out
    assert "inbox_write_failed" in out
    assert "notFound" in out
    assert "김상담" not in out
    assert _FOLDER_ID not in out


def test_write_success_log_has_file_id_but_no_file_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")
    factory = _Factory([(_SESSION, ""), _CREATED])

    _write(_writer(factory))

    out = capsys.readouterr().out
    assert "inbox_written" in out
    assert "FILE123" in out
    assert "김상담" not in out
    assert _FOLDER_ID not in out


def test_write_maps_network_error() -> None:
    def broken(timeout: float) -> Any:
        raise ConnectionResetError

    with pytest.raises(InboxUnavailableError) as exc_info:
        _write(DriveInboxWriter(_FOLDER_ID, http_factory=broken))

    assert exc_info.value.reason == "ConnectionResetError"


def test_unexpected_error_is_not_converted() -> None:
    def buggy(timeout: float) -> Any:
        raise KeyError("bug")

    with pytest.raises(KeyError):
        _write(DriveInboxWriter(_FOLDER_ID, http_factory=buggy))


# ---------------------------------------------------------------- 자격 증명


def test_credentials_are_not_loaded_on_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(**kwargs: Any) -> Any:
        raise AssertionError("시작 시 자격 증명을 읽으면 안 된다")

    monkeypatch.setattr("google.auth.default", fail)

    DriveInboxWriter(_FOLDER_ID)


@pytest.mark.parametrize("error_type", [DefaultCredentialsError, RefreshError])
def test_credential_error_becomes_unavailable(
    monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    calls: list[dict[str, Any]] = []

    def fail(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise error_type("no key")

    monkeypatch.setattr("google.auth.default", fail)

    with pytest.raises(InboxUnavailableError) as exc_info:
        DriveInboxWriter(_FOLDER_ID).check()

    assert exc_info.value.reason == error_type.__name__
    assert calls == [{"scopes": DRIVE_SCOPES}]


def test_default_http_loads_credentials_once_and_sets_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loads: list[Any] = []
    timeouts: list[float] = []
    http = HttpMockSequence([({"status": "200"}, json.dumps(_FOLDER_OK))] * 2)

    def fake_default(**kwargs: Any) -> Any:
        loads.append(kwargs)
        return AnonymousCredentials(), None  # type: ignore[no-untyped-call]

    def fake_http(timeout: float) -> Any:
        timeouts.append(timeout)
        return http

    monkeypatch.setattr("google.auth.default", fake_default)
    monkeypatch.setattr("httplib2.Http", fake_http)
    writer = DriveInboxWriter(_FOLDER_ID)

    writer.check()
    writer.check()

    assert loads == [{"scopes": DRIVE_SCOPES}]
    assert timeouts == [5.0, 5.0]  # 호출마다 새 Http


# ---------------------------------------------------------------- check


def test_check_reads_folder_metadata_only() -> None:
    factory = _Factory([({"status": "200"}, json.dumps(_FOLDER_OK))])

    _writer(factory).check()

    ((uri, method, _, _),) = factory.requests
    query = parse_qs(urlsplit(uri).query)
    assert method == "GET"
    assert urlsplit(uri).path == f"/drive/v3/files/{_FOLDER_ID}"
    assert query["supportsAllDrives"] == ["true"]
    assert query["fields"] == ["id,mimeType,trashed,capabilities/canAddChildren"]
    assert factory.timeouts == [5.0]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"mimeType": "audio/wav"}, "not_folder"),
        ({"trashed": True}, "trashed"),
        ({"capabilities": {"canAddChildren": False}}, "cannot_add_children"),
    ],
)
def test_check_rejects_unusable_folder(change: dict[str, Any], reason: str) -> None:
    factory = _Factory([({"status": "200"}, json.dumps(_FOLDER_OK | change))])

    with pytest.raises(InboxUnavailableError) as exc_info:
        _writer(factory).check()

    assert exc_info.value.reason == reason


def test_check_does_not_retry() -> None:
    factory = _Factory([({"status": "503"}, "")])

    with pytest.raises(InboxUnavailableError) as exc_info:
        _writer(factory).check()

    assert exc_info.value.reason == "http_503"
    assert len(factory.requests) == 1
