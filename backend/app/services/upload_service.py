"""웹 업로드 유스케이스 (W-07): 파일명·형식 검증 후 inbox/에 쓴다. DB는 쓰지 않는다."""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import BinaryIO

import structlog

from app.core.config import AudioExtension
from app.core.errors import AppError, ErrorCode
from app.infra.inbox import InboxUnavailableError, InboxWriter
from app.infra.inbox.local import validate_local_name
from app.schemas.upload import UploadedFile, UploadResponse

MAX_FILES_PER_REQUEST = 10
MAX_NAME_LENGTH = 255  # NTFS 경로 성분 한도(UTF-16 코드 단위)
HEAD_BYTES = 12  # 매직 바이트 판정에 읽는 앞부분 길이
_TOO_MANY_FILES_MSG = f"파일은 한 번에 최대 {MAX_FILES_PER_REQUEST}개까지 올릴 수 있습니다"

# Drive mimeType으로 넘기는 정규 MIME. 클라이언트가 보낸 Content-Type은 쓰지 않는다.
CANONICAL_MIME: dict[AudioExtension, str] = {"wav": "audio/wav", "mp3": "audio/mpeg"}

_log = structlog.stdlib.get_logger("app.upload")


@dataclass(frozen=True)
class IncomingFile:
    """라우터가 넘기는 업로드 파일 하나. stream은 seek 가능한 원본(UploadFile.file)."""

    filename: str | None
    stream: BinaryIO


@dataclass(frozen=True)
class _CheckedFile:
    name: str
    stream: BinaryIO
    content_type: str


def normalize_filename(raw: str | None) -> str | None:
    """경로 성분을 떼고 NFC로 정규화한다. inbox/·로봇 PC(Windows)에 쓸 수 없는 이름이면 None.

    금지 문자·제어 문자·앞뒤 공백·끝 점·255자 초과는 치환하지 않고 거절한다.
    """
    if not raw:
        return None
    name = unicodedata.normalize("NFC", raw.replace("\\", "/").rsplit("/", 1)[-1])
    try:
        validate_local_name(name)  # "", ".", "..", \ / : * ? " < > |, 제어 문자(< 32)
    except ValueError:
        return None
    if name != name.strip() or name.endswith("."):
        return None
    if len(name.encode("utf-16-le")) // 2 > MAX_NAME_LENGTH:
        return None
    return name


def detect_audio_format(head: bytes) -> AudioExtension | None:
    """앞부분으로 형식을 판정한다. WAV = RIFF…WAVE, MP3 = ID3 태그 또는 Layer III 프레임 동기."""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:3] == b"ID3":
        return "mp3"
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:
        version = (head[1] >> 3) & 0b11  # 01은 예약값
        layer = (head[1] >> 1) & 0b11  # 01 = Layer III (00이면 ADTS AAC)
        if version != 0b01 and layer == 0b01:
            return "mp3"
    return None


def _filename_error(index: int) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        detail={
            "errors": [
                {
                    "loc": ["body", "files", index],
                    "msg": "사용할 수 없는 파일명입니다",
                    "type": "filename_invalid",
                }
            ]
        },
    )


def _unsupported(index: int) -> AppError:
    return AppError(ErrorCode.UNSUPPORTED_MEDIA, detail={"index": index})


class UploadService:
    def __init__(
        self, writer: InboxWriter | None, allowed_extensions: Sequence[AudioExtension]
    ) -> None:
        self._writer = writer
        self._allowed = frozenset(allowed_extensions)

    def upload(self, files: Sequence[IncomingFile]) -> UploadResponse:
        if self._writer is None:  # INBOX_BACKEND=disabled: 무엇을 올려도 소용없으므로 검증보다 먼저
            raise AppError(ErrorCode.INBOX_UNAVAILABLE)
        if len(files) > MAX_FILES_PER_REQUEST:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                detail={
                    "errors": [
                        {
                            "loc": ["body", "files"],
                            "msg": _TOO_MANY_FILES_MSG,
                            "type": "too_many_files",
                        }
                    ]
                },
            )
        # 전부 검증한 뒤에 올린다: 검증 실패로 일부만 inbox/에 들어가는 일이 없다.
        checked = [self._check(index, file) for index, file in enumerate(files)]
        for written, item in enumerate(checked):
            try:
                self._writer.write(item.name, item.stream, item.content_type)
            except InboxUnavailableError as exc:
                # 원인 예외(__cause__)에 키 경로 등이 있을 수 있어 exc_info 없이 reason만 남긴다.
                _log.warning(
                    "upload_aborted", reason=exc.reason, written=written, files=len(checked)
                )
                raise AppError(ErrorCode.INBOX_UNAVAILABLE) from None
        _log.info("upload_accepted", files=len(checked))
        return UploadResponse(items=[UploadedFile(name=item.name) for item in checked])

    def _check(self, index: int, file: IncomingFile) -> _CheckedFile:
        name = normalize_filename(file.filename)
        if name is None:
            raise _filename_error(index)
        stem, dot, ext = name.rpartition(".")
        if not dot:
            raise _unsupported(index)  # 확장자 없음
        if not stem:
            raise _filename_error(index)  # ".wav"처럼 확장자만 있는 이름
        ext = ext.lower()
        if ext not in self._allowed:
            raise _unsupported(index)
        file.stream.seek(0)
        head = file.stream.read(HEAD_BYTES)
        file.stream.seek(0)
        detected = detect_audio_format(head)
        if detected is None or detected != ext:
            raise _unsupported(index)  # 빈 파일·다른 형식·확장자와 내용 불일치
        return _CheckedFile(f"{stem}.{detected}", file.stream, CANONICAL_MIME[detected])
