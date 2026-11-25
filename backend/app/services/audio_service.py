"""음성 재생 유스케이스 (W-06): 상담 건의 음성 사본을 찾아 요청 구간만 읽을 스트림을 연다."""

from dataclasses import dataclass
from typing import BinaryIO

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audio_format import CANONICAL_MIME
from app.core.errors import AppError, ErrorCode
from app.core.http_range import parse_range
from app.infra.storage import AudioNotFoundError, AudioStorage
from app.models import CallRecord

# 저장소 키 확장자 → 정규 MIME. 확장자는 등록 시 매직 바이트로 정한 실제 형식이다.
_MEDIA_TYPES: dict[str, str] = {f".{ext}": mime for ext, mime in CANONICAL_MIME.items()}

_log = structlog.stdlib.get_logger("app.audio")


@dataclass(frozen=True)
class AudioContent:
    """열린 음성 스트림과 응답 헤더 계산에 필요한 값. stream은 호출자가 닫는다."""

    stream: BinaryIO
    media_type: str
    extension: str  # ".wav" / ".mp3"
    size: int  # 파일 전체 크기
    byte_range: tuple[int, int] | None  # (시작, 끝) 끝 포함. None이면 전체

    @property
    def length(self) -> int:
        """보낼 바이트 수 (Content-Length)."""
        if self.byte_range is None:
            return self.size
        start, end = self.byte_range
        return end - start + 1


class AudioService:
    def __init__(self, db: Session, storage: AudioStorage) -> None:
        self._db = db
        self._storage = storage

    def open_audio(self, call_id: int, range_header: str | None) -> AudioContent:
        """삭제되지 않은 건의 음성을 연다.

        없는 건·삭제된 건·사본 파일이 없는 건은 404. 범위가 파일 밖이면 RangeNotSatisfiableError.
        키 형식 오류(InvalidKeyError)·디스크 오류(OSError)는 그대로 올려 500이 된다.
        """
        key = self._db.scalar(
            select(CallRecord.object_key).where(
                CallRecord.id == call_id, CallRecord.deleted_at.is_(None)
            )
        )
        if key is None:
            raise AppError(ErrorCode.NOT_FOUND)
        media_type = _MEDIA_TYPES[key[key.rfind(".") :]]  # 표에 없으면 KeyError → 500
        try:
            size = self._storage.size(key)
            byte_range = parse_range(range_header, size)
            stream = self._storage.open(key, byte_range)
        except AudioNotFoundError:
            # 레코드는 있는데 사본이 없다(정리 배치·운영 사고). 키는 로그에 남기지 않는다.
            _log.warning("audio_missing", call_id=call_id)
            raise AppError(ErrorCode.NOT_FOUND) from None
        audio = AudioContent(stream, media_type, key[key.rfind(".") :], size, byte_range)
        _log.info(
            "audio_access",
            call_id=call_id,
            range_start=byte_range[0] if byte_range else None,
            range_end=byte_range[1] if byte_range else None,
            status=206 if byte_range else 200,
            bytes=audio.length,
        )
        return audio
