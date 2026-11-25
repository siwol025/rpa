"""웹 재처리 요청 유스케이스 (W-05).

전이·`retry_count` +1·`processing_log` 기록·404·409·행 잠금은 상태 머신(R-02)이 한다.
이 서비스는 임시 가드와 커밋만 더한다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import CallRecord
from app.schemas.call import CallStatus
from app.schemas.retry import RetryResult
from app.services.state_machine import CallStateMachine, InvalidTransition


class RetryService:
    def __init__(self, db: Session, *, stale_threshold_min: int) -> None:
        self._db = db
        self._machine = CallStateMachine(db, stale_threshold_min=stale_threshold_min)

    def request_retry(self, call_id: int) -> RetryResult:
        """건을 `RETRY_REQUESTED`로 바꾼다. 실제 재처리는 다음 Dispatcher 주기에 일어난다.

        허용: `FAILED`·`NEEDS_REVIEW`·`STORED`, 정체된 `REGISTERED`·`QUEUED`·`STT_DONE`.
        없는(또는 소프트 삭제된) 건은 404, 그 밖의 상태는 409 `INVALID_STATE_TRANSITION`.
        """
        self._reject_already_requested(call_id)
        call = self._machine.transition(call_id, CallStatus.RETRY_REQUESTED, actor="web")
        # 커밋하면 속성이 만료돼 다시 SELECT하므로 커밋 전에 응답 값을 꺼내 둔다.
        result = RetryResult(call_id=call.id, status=call.status, retry_count=call.retry_count)
        self._db.commit()
        return result

    def _reject_already_requested(self, call_id: int) -> None:
        """[임시 가드] 이미 `RETRY_REQUESTED`인 건은 정체 여부와 관계없이 409.

        상태 머신은 정체된 `RETRY_REQUESTED`의 재요청도 허용하지만, 문서·프론트는 이를
        Dispatcher 정지(로봇 점검 대상)로 보고 재처리 대상에서 뺀다. 상태 머신의 정체 재처리
        대상이 `REGISTERED`·`QUEUED`·`STT_DONE`으로 좁혀지면 이 메서드와 호출 1줄을 지운다.

        첫 조회부터 행 잠금(FOR UPDATE)으로 읽고 `populate_existing`으로 세션에 남은 객체를
        DB 값으로 덮어쓴다. 잠금 없이 먼저 읽으면 뒤이은 `transition`의 잠금 조회가 식별자 맵의
        낡은 객체를 돌려받아 정체 판정이 틀어진다.
        """
        call = self._db.scalars(
            select(CallRecord)
            .where(CallRecord.id == call_id, CallRecord.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if call is None:
            raise AppError(ErrorCode.NOT_FOUND)
        if call.status == CallStatus.RETRY_REQUESTED:
            raise InvalidTransition(call.status, CallStatus.RETRY_REQUESTED)
