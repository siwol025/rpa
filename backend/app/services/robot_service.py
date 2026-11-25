"""로봇(UiPath)이 호출하는 등록·적재 유스케이스 (R-04~R-08)."""

import hashlib
from pathlib import Path
from typing import BinaryIO, cast

import filetype
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.infra.storage import AudioNotFoundError, AudioStorage, InvalidKeyError
from app.models import Analysis, CallRecord, ProcessingLog, Transcript
from app.schemas.call import CATEGORY_DB_VALUES, CallStatus, LogStatus, LogStep
from app.schemas.robot import (
    CATEGORY_BY_ANALYSIS_TYPE,
    RobotAnalysisRequest,
    RobotCallForm,
    RobotLogRequest,
    RobotTranscriptRequest,
)
from app.services.state_machine import CallStateMachine, InvalidTransition

# 파일 시그니처(매직 바이트)로 판별한 MIME → 저장 확장자. 확장자·Content-Type은 믿지 않는다.
_EXTENSION_BY_MIME = {"audio/x-wav": ".wav", "audio/mpeg": ".mp3"}
RETRY_TARGET_LIMIT = 100  # 재처리 대상 조회 상한 (convention.md §4)
_SIGNATURE_BYTES = 262  # filetype이 판별에 쓰는 최대 길이

# 처리 결과가 저장된 상태. 이후 로봇의 재전송은 같은 내용일 때만 받는다.
_RESULT_STATES = frozenset({CallStatus.STORED, CallStatus.NEEDS_REVIEW})
# 이 상태에서 보낸 FAIL은 전이 없이 로그만 남긴다 (처리는 끝났고 엑셀 기입 등 뒷단계만 실패).
_LOG_ONLY_ON_FAIL = frozenset({CallStatus.STORED, CallStatus.NEEDS_REVIEW, CallStatus.FAILED})


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

        멱등: 이미 `STT_DONE`이면 전이 없이 전사만 덮어쓴다. 처리가 끝난(`STORED`·`NEEDS_REVIEW`)
        뒤에는 저장된 전사와 같은 내용일 때만 그대로 성공한다(응답을 못 받은 Performer의 Queue
        재시도). 다른 내용이거나 그 밖의 상태면 409라서 이미 저장된 결과를 덮어쓰지 않는다.
        """
        call = self._lock_call(call_id)
        segments = [segment.model_dump(mode="json") for segment in body.segments]
        transcript = self._db.scalars(
            select(Transcript).where(Transcript.call_id == call_id)
        ).one_or_none()

        if call.status in _RESULT_STATES:
            if (
                transcript is not None
                and transcript.segments == segments
                and transcript.corrected_text == body.full_text
                and transcript.stt_engine == body.stt_engine
            ):
                return call
            raise InvalidTransition(call.status, CallStatus.STT_DONE)
        if call.status != CallStatus.STT_DONE:
            self._machine.transition(call_id, CallStatus.STT_DONE, actor="robot")

        if transcript is None:
            transcript = Transcript(call_id=call_id, segments=[])
            self._db.add(transcript)
        transcript.segments = segments
        # 마스킹된 전체 텍스트를 corrected_text에 둔다 (키워드 검색 pg_trgm 대상).
        transcript.corrected_text = body.full_text
        transcript.stt_engine = body.stt_engine
        self._db.commit()
        return call

    def put_analysis(self, call_id: int, body: RobotAnalysisRequest) -> CallRecord:
        """분석 결과를 저장하고 `STT_DONE` → `STORED` / `NEEDS_REVIEW`로 전이한다 (R-07).

        검토 필요 여부는 GenAI 결과의 `status`를 그대로 따른다 (임계값으로 다시 판정하지 않음).
        멱등: 이미 같은 결과 상태면 전이 없이 분석만 덮어쓴다. 다른 상태면 409.
        재분석 시 `action_status`는 사람이 바꿨을 수 있으므로 덮어쓰지 않는다.
        """
        call = self._lock_call(call_id)
        target = CallStatus.NEEDS_REVIEW if body.status == "NEEDS_REVIEW" else CallStatus.STORED
        if call.status == CallStatus.STT_DONE:
            self._machine.transition(call_id, target, actor="robot")
        elif call.status != target:
            # NEEDS_REVIEW → STORED(검토 완료)는 웹의 몫이다. 로봇이 결과를 다시 보내 넘기지 못한다.
            raise InvalidTransition(call.status, target)

        analysis = self._db.scalars(
            select(Analysis).where(Analysis.call_id == call_id)
        ).one_or_none()
        if analysis is None:
            analysis = Analysis(call_id=call_id)
            self._db.add(analysis)
        category = CATEGORY_BY_ANALYSIS_TYPE[body.type]
        analysis.category = CATEGORY_DB_VALUES[category]
        analysis.confidence = body.type_confidence  # type: ignore[assignment]
        analysis.question_summary = body.customer_question
        analysis.action_summary = body.agent_action
        analysis.follow_up_required = body.follow_up_required
        analysis.entities = [entity.model_dump() for entity in body.entities]
        analysis.prompt_version = body.processing.prompt_version if body.processing else None
        analysis.needs_review = target == CallStatus.NEEDS_REVIEW
        # 전사는 transcript 테이블에 이미 있으므로 원본에서 뺀다 (본문 중복 저장 방지).
        analysis.raw_json = body.model_dump(mode="json", exclude={"transcript"})
        self._db.commit()
        return call

    def add_log(self, call_id: int, body: RobotLogRequest) -> CallRecord:
        """단계 로그를 기록한다. 처리 중인 건의 `FAIL`이면 `FAILED`로 전이한다 (R-08).

        `STORED`·`NEEDS_REVIEW` 건의 `FAIL`(엑셀 기입 실패 등)은 상태를 두고 로그만 남긴다.
        이미 `FAILED`인 건의 `FAIL` 재전송도 로그만 남긴다. 정체 후 재처리된
        (`RETRY_REQUESTED`) 건에 이전 Queue 건이 뒤늦게 보낸 `FAIL`은 409다.
        """
        call = self._lock_call(call_id)
        message = (
            f"[{body.stage}] {body.message}"
            if body.stage and body.message
            else (f"[{body.stage}]" if body.stage else body.message)
        )

        if body.status == LogStatus.FAIL and call.status not in _LOG_ONLY_ON_FAIL:
            self._machine.transition(
                call_id,
                CallStatus.FAILED,
                actor="robot",
                reason=message,
                step=body.step,
                log_status=LogStatus.FAIL,
                orchestrator_job_id=body.orchestrator_job_id,
            )
        else:
            self._db.add(
                ProcessingLog(
                    call_id=call_id,
                    step=body.step,
                    status=body.status,
                    message=f"[robot] {message}" if message else "[robot]",
                    orchestrator_job_id=body.orchestrator_job_id,
                )
            )
        self._db.commit()
        return call

    def list_retry_targets(self, limit: int = RETRY_TARGET_LIMIT) -> list[CallRecord]:
        """`RETRY_REQUESTED` 건을 오래 기다린 순으로 돌려준다 (R-09)."""
        return list(
            self._db.scalars(
                select(CallRecord)
                .where(
                    CallRecord.status == CallStatus.RETRY_REQUESTED, CallRecord.deleted_at.is_(None)
                )
                .order_by(CallRecord.status_changed_at, CallRecord.id)
                .limit(limit)
            )
        )

    def open_audio(self, call_id: int) -> tuple[BinaryIO, int, str]:
        """음성 사본의 (스트림, 크기, 확장자)를 돌려준다 (R-10). 호출자가 스트림을 닫는다.

        건이 없거나 삭제됐거나 사본이 저장소에 없으면 404.
        """
        call = self._db.scalars(
            select(CallRecord).where(CallRecord.id == call_id, CallRecord.deleted_at.is_(None))
        ).one_or_none()
        if call is None:
            raise AppError(ErrorCode.NOT_FOUND)
        try:
            size = self._storage.size(call.object_key)
            stream = self._storage.open(call.object_key)
        except (AudioNotFoundError, InvalidKeyError):
            raise AppError(ErrorCode.NOT_FOUND) from None
        return stream, size, Path(call.object_key).suffix

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
