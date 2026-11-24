"""로봇(UiPath)이 호출하는 등록·적재 유스케이스 (R-04~R-08)."""

import hashlib
from typing import BinaryIO, cast

import filetype
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.infra.storage import AudioStorage
from app.models import CallRecord, ProcessingLog, Transcript
from app.schemas.call import CallStatus, LogStatus, LogStep
from app.schemas.robot import RobotCallForm, RobotTranscriptRequest
from app.services.state_machine import CallStateMachine

# 파일 시그니처(매직 바이트)로 판별한 MIME → 저장 확장자. 확장자·Content-Type은 믿지 않는다.
_EXTENSION_BY_MIME = {"audio/x-wav": ".wav", "audio/mpeg": ".mp3"}
_SIGNATURE_BYTES = 262  # filetype이 판별에 쓰는 최대 길이


class _HashingReader:
    """읽는 만큼 SHA-256·크기를 계산하는 래퍼. 저장하면서 해시를 구해 파일을 두 번 읽지 않는다."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._digest = hashlib.sha256()
        self.size = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        self._digest.update(chunk)
        self.size += len(chunk)
        return chunk

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


class RobotService:
    def __init__(self, db: Session, storage: AudioStorage, *, stale_threshold_min: int) -> None:
        self._db = db
        self._storage = storage
        self._machine = CallStateMachine(db, stale_threshold_min=stale_threshold_min)

    def register_call(self, upload: BinaryIO, form: RobotCallForm) -> CallRecord:
        """음성 사본을 저장하고 `REGISTERED`로 등록한다 (R-04).

        같은 해시가 이미 있으면 409 `DUPLICATE_FILE`(`detail.existing_id`·`detail.status`).
        DB 등록이 실패하면 저장한 사본을 지운다(보상 처리).
        """
        existing = self._find_by_hash(form.file_hash)
        if existing is not None:
            raise _duplicate(existing)

        extension = _detect_extension(upload)
        reader = _HashingReader(upload)
        key = self._storage.save(cast(BinaryIO, reader), extension=extension)
        try:
            call = self._create_record(form, key, reader)
            self._db.commit()
        except BaseException:
            self._storage.delete(key)
            raise
        return call

    def mark_queued(self, call_id: int, queue_item_id: int) -> CallRecord:
        """`REGISTERED`·`RETRY_REQUESTED` 건을 `QUEUED`로 바꾸고 Queue Item ID를 기록한다 (R-05).

        같은 `queue_item_id`로 이미 `QUEUED`면 그대로 성공한다 (응답을 못 받은 Dispatcher의 재시도).
        다른 ID로 `QUEUED`이거나 그 밖의 상태면 409.
        """
        call = self._lock_call(call_id)
        if call.status == CallStatus.QUEUED and call.queue_item_id == queue_item_id:
            return call

        self._machine.transition(
            call_id, CallStatus.QUEUED, actor="robot", reason=f"queue_item_id={queue_item_id}"
        )
        call.queue_item_id = queue_item_id
        self._db.commit()
        return call

    def put_transcript(self, call_id: int, body: RobotTranscriptRequest) -> CallRecord:
        """전사를 저장하고 `QUEUED` → `STT_DONE`으로 전이한다 (R-06).

        멱등: 이미 `STT_DONE`이면 전이 없이 전사만 덮어쓴다 (Queue 재시도로 다시 불려도 같은 결과).
        그 밖의 상태는 409.
        """
        call = self._lock_call(call_id)
        if call.status != CallStatus.STT_DONE:
            self._machine.transition(call_id, CallStatus.STT_DONE, actor="robot")

        transcript = self._db.scalars(
            select(Transcript).where(Transcript.call_id == call_id)
        ).one_or_none()
        if transcript is None:
            transcript = Transcript(call_id=call_id, segments=[])
            self._db.add(transcript)
        transcript.segments = [segment.model_dump(mode="json") for segment in body.segments]
        # 마스킹된 전체 텍스트를 corrected_text에 둔다 (키워드 검색 pg_trgm 대상).
        transcript.corrected_text = body.full_text
        transcript.stt_engine = body.stt_engine
        self._db.commit()
        return call

    def _lock_call(self, call_id: int) -> CallRecord:
        """행 잠금을 걸고 건을 읽는다. 없거나 소프트 삭제된 건은 404."""
        call = self._db.scalars(
            select(CallRecord)
            .where(CallRecord.id == call_id, CallRecord.deleted_at.is_(None))
            .with_for_update()
        ).one_or_none()
        if call is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return call

    def _create_record(self, form: RobotCallForm, key: str, reader: _HashingReader) -> CallRecord:
        if reader.hexdigest() != form.file_hash:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                detail={
                    "errors": [
                        {
                            "loc": ["body", "file_hash"],
                            "msg": "file_hash가 파일 내용의 SHA-256과 다릅니다",
                            "type": "hash_mismatch",
                        }
                    ]
                },
            )

        call = CallRecord(
            source_type=form.source_type,
            source_ref=form.source_ref,
            object_key=key,
            original_name=form.original_name,
            file_hash=form.file_hash,
            file_size=reader.size,
            agent_name=form.agent_name,
            client_company=form.client_company,
            call_datetime=form.call_datetime,
            metadata_incomplete=form.agent_name is None or form.call_datetime is None,
            status=CallStatus.REGISTERED,
        )
        try:
            # 동시에 같은 파일을 등록하면 해시 유니크 인덱스가 막는다. 세이브포인트로 감싸
            # 실패해도 같은 세션에서 기존 건을 다시 조회할 수 있게 한다.
            with self._db.begin_nested():
                self._db.add(call)
                self._db.flush()
        except IntegrityError:
            existing = self._find_by_hash(form.file_hash)
            if existing is None:
                raise
            raise _duplicate(existing) from None

        self._db.add(
            ProcessingLog(
                call_id=call.id,
                step=LogStep.REGISTER,
                status=LogStatus.SUCCESS,
                message="[robot] registered",
            )
        )
        return call

    def _find_by_hash(self, file_hash: str) -> CallRecord | None:
        return self._db.scalars(
            select(CallRecord).where(
                CallRecord.file_hash == file_hash, CallRecord.deleted_at.is_(None)
            )
        ).one_or_none()


def _detect_extension(upload: BinaryIO) -> str:
    head = upload.read(_SIGNATURE_BYTES)
    upload.seek(0)
    kind = filetype.guess(head)
    extension = _EXTENSION_BY_MIME.get(kind.mime) if kind is not None else None
    if extension is None:
        raise AppError(ErrorCode.UNSUPPORTED_MEDIA, message="wav, mp3 파일만 등록할 수 있습니다.")
    return extension


def _duplicate(existing: CallRecord) -> AppError:
    return AppError(
        ErrorCode.DUPLICATE_FILE,
        detail={"existing_id": existing.id, "status": existing.status},
    )
