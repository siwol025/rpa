"""Google Drive 공유 드라이브 inbox/ 업로드 (서비스 계정, Drive API v3)."""

import random
import time
from collections.abc import Callable
from typing import Any, BinaryIO, NoReturn

import google.auth
import httplib2
import structlog
from google.auth.credentials import Credentials
from google.auth.exceptions import GoogleAuthError
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from app.infra.inbox.base import InboxUnavailableError

_log = structlog.stdlib.get_logger("app.inbox")

# drive.file로 기존 inbox/ 폴더에 쓸 수 있는지는 E-01 이후 실측한다. 안 되면 drive로 바꾼다.
DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive.file",)
# Dispatcher가 source_type=WEB 판정에 쓰는 공개 속성 (모든 앱이 읽을 수 있는 properties).
SOURCE_PROPERTY = {"source": "web"}

_RETRIES = 2  # 지수 백오프 재시도 횟수 (architecture.md §8.2)
_RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})
_UPLOAD_TIMEOUT_SEC = 30.0  # 소켓 무응답 한도. 라이브러리 기본 60초는 재시도와 겹치면 너무 길다
_CHECK_TIMEOUT_SEC = 5.0
_FOLDER_MIME = "application/vnd.google-apps.folder"
_CHECK_FIELDS = "id,mimeType,trashed,capabilities/canAddChildren"

# 요청 타임아웃(초) → 새 Http. httplib2는 스레드 안전하지 않아 호출마다 새로 만든다.
HttpFactory = Callable[[float], httplib2.Http]

# 라이브러리·인증·네트워크 오류. 그 밖의 예외(버그)는 그대로 올려 500이 되게 한다.
_DRIVE_ERRORS = (HttpError, GoogleAuthError, httplib2.HttpLib2Error, OSError)


class _ServiceAccountHttp:
    """ADC(GOOGLE_APPLICATION_CREDENTIALS 또는 GCP 메타데이터)로 인증된 Http를 만든다.

    자격 증명은 첫 호출 때 읽는다: 키 파일 문제로 앱 시작이 막히지 않게 한다.
    """

    def __init__(self) -> None:
        self._credentials: Credentials | None = None

    def __call__(self, timeout: float) -> httplib2.Http:
        if self._credentials is None:
            self._credentials, _ = google.auth.default(scopes=DRIVE_SCOPES)
        return AuthorizedHttp(self._credentials, http=httplib2.Http(timeout=timeout))


def _reason(exc: Exception) -> str:
    # HttpError 원문(str)·uri에는 폴더 ID·업로드 세션 URI가 들어갈 수 있어 상태 코드만 쓴다.
    if isinstance(exc, HttpError):
        return f"http_{exc.status_code}"
    return type(exc).__name__


def _drive_reason(exc: Exception) -> str | None:
    if isinstance(exc, HttpError) and exc.error_details:
        detail = exc.error_details[0]
        if isinstance(detail, dict):
            value = detail.get("reason")
            return str(value) if value is not None else None
    return None


def _is_retryable(exc: Exception) -> bool:
    # 5xx·429·403 rate limit·네트워크 오류만 재시도. 권한·404·400·인증 오류는 즉시 실패.
    if isinstance(exc, HttpError):
        status = exc.status_code
        return bool(
            status >= 500
            or status == 429
            or (status == 403 and _drive_reason(exc) in _RATE_LIMIT_REASONS)
        )
    return isinstance(exc, OSError | httplib2.HttpLib2Error)


def _upload(request: Any) -> Any:
    """resumable 업로드를 끝까지 진행한다. 실패한 단계는 지수 백오프로 최대 _RETRIES회 재시도한다.

    라이브러리 내장 재시도(execute(num_retries=...))는 PUT 재시도 때 이미 읽은 스트림 조각을
    되감지 않아 빈 본문을 보내고, PUT 중 소켓 오류는 재시도하지 않는다. 그래서 next_chunk를
    한 번씩 직접 다시 부른다: 오류 뒤 다시 부르면 서버가 받은 위치를 조회
    (Content-Range: bytes */N)한 뒤 그 위치부터 새 조각으로 재전송한다.
    세션 POST 실패도 같은 루프에서 POST부터 다시 한다.
    """
    attempt = 0
    while True:
        try:
            _, response = request.next_chunk(num_retries=0)
        except (HttpError, httplib2.HttpLib2Error, OSError) as exc:
            if attempt >= _RETRIES or not _is_retryable(exc):
                raise
            attempt += 1
            time.sleep(random.random() * 2**attempt)
            continue
        if response is not None:
            return response


class DriveInboxWriter:
    def __init__(self, folder_id: str, *, http_factory: HttpFactory | None = None) -> None:
        self._folder_id = folder_id
        self._http_factory: HttpFactory = http_factory or _ServiceAccountHttp()

    def _service(self, timeout: float) -> Any:
        # 동봉된 discovery 문서를 쓰므로 네트워크 호출이 없다.
        return build("drive", "v3", http=self._http_factory(timeout), cache_discovery=False)

    def write(self, filename: str, stream: BinaryIO, content_type: str) -> str:
        body = {"name": filename, "parents": [self._folder_id], "properties": SOURCE_PROPERTY}
        try:
            media = MediaIoBaseUpload(stream, mimetype=content_type, resumable=True)
            request = (
                self._service(_UPLOAD_TIMEOUT_SEC)
                .files()
                .create(body=body, media_body=media, fields="id", supportsAllDrives=True)
            )
            response = _upload(request)
        except _DRIVE_ERRORS as exc:
            self._fail("inbox_write_failed", exc)
        file_id = str(response["id"])
        _log.info("inbox_written", backend="drive", file_id=file_id, size_bytes=media.size())
        return file_id

    def check(self) -> None:
        try:
            meta = (
                self._service(_CHECK_TIMEOUT_SEC)
                .files()
                .get(fileId=self._folder_id, fields=_CHECK_FIELDS, supportsAllDrives=True)
                .execute(num_retries=0)
            )
        except _DRIVE_ERRORS as exc:
            self._fail("inbox_check_failed", exc)
        if meta.get("mimeType") != _FOLDER_MIME:
            raise InboxUnavailableError("not_folder")
        if meta.get("trashed"):
            raise InboxUnavailableError("trashed")
        if not meta.get("capabilities", {}).get("canAddChildren"):
            raise InboxUnavailableError("cannot_add_children")

    def _fail(self, event: str, exc: Exception) -> NoReturn:
        reason = _reason(exc)
        _log.warning(event, backend="drive", reason=reason, drive_reason=_drive_reason(exc))
        raise InboxUnavailableError(reason) from exc
