"""처리 상태 머신 (R-02). 상태 전이는 이 모듈에서만 수행한다 (features_backend_A.md §2).

호출자는 로봇 API(R-05~R-08)와 웹 API(W-03 검토 완료, W-05 재처리)다.

- 행 잠금(`SELECT ... FOR UPDATE`)으로 로봇·웹 동시 전이를 직렬화한다.
- `flush`까지만 한다. 커밋은 호출자가 한다 (전사·분석 적재와 전이를 한 트랜잭션으로 묶기 위해).
- 허용되지 않은 전이는 `InvalidTransition`(409, 현재 상태 포함).
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.models import CallRecord, ProcessingLog
from app.schemas.call import CallStatus, LogStatus, LogStep

S = CallStatus

# 정체 판단 없이 허용되는 전이 (현재 상태 → 다음 상태들)
_ALLOWED: dict[CallStatus, frozenset[CallStatus]] = {
    S.REGISTERED: frozenset({S.QUEUED, S.FAILED}),
    S.QUEUED: frozenset({S.STT_DONE, S.FAILED}),
    S.STT_DONE: frozenset({S.STORED, S.NEEDS_REVIEW, S.FAILED}),
    S.NEEDS_REVIEW: frozenset({S.STORED, S.RETRY_REQUESTED}),
    S.STORED: frozenset({S.RETRY_REQUESTED}),
    S.FAILED: frozenset({S.RETRY_REQUESTED}),
    S.RETRY_REQUESTED: frozenset({S.QUEUED}),
}

# 처리 중 상태. 정체 시간을 넘기면 재처리 요청(RETRY_REQUESTED)으로 전이할 수 있다.
STALE_ELIGIBLE: frozenset[CallStatus] = frozenset(
    {S.REGISTERED, S.QUEUED, S.STT_DONE, S.RETRY_REQUESTED}
)

# 전이 로그의 기본 단계. 로봇이 단계를 알려 주면(R-08 stage) `step`으로 덮어쓴다.
_STEP_BY_TARGET: dict[CallStatus, LogStep] = {
    S.REGISTERED: LogStep.REGISTER,
    S.QUEUED: LogStep.QUEUE,
    S.STT_DONE: LogStep.STT,
    S.STORED: LogStep.STORE,
    S.NEEDS_REVIEW: LogStep.STORE,
    S.RETRY_REQUESTED: LogStep.RETRY,
}
# 실패는 직전 상태가 곧 실패한 단계다 (STT_DONE 이후 실패 = 분석 단계).
_FAILED_STEP_BY_SOURCE: dict[CallStatus, LogStep] = {
    S.REGISTERED: LogStep.REGISTER,
    S.QUEUED: LogStep.STT,
    S.STT_DONE: LogStep.GENAI,
}


class InvalidTransition(AppError):  # noqa: N818 (B와 합의한 인터페이스 이름)
    """허용되지 않은 전이. 409 `INVALID_STATE_TRANSITION`, detail에 현재·요청 상태."""

    def __init__(self, current_status: str, requested_status: str) -> None:
        self.current_status = current_status
        self.requested_status = requested_status
        super().__init__(
            ErrorCode.INVALID_STATE_TRANSITION,
            detail={"current_status": current_status, "requested_status": requested_status},
        )


def is_stale(call: CallRecord, threshold_min: int, now: datetime | None = None) -> bool:
    """처리 중 상태로 `threshold_min`분을 넘게 머물렀는가. (R-11 정체 감지도 같은 기준)"""
    if call.status not in STALE_ELIGIBLE:
        return False
    now = now or datetime.now(UTC)
    return call.status_changed_at < now - timedelta(minutes=threshold_min)


class CallStateMachine:
    def __init__(self, db: Session, *, stale_threshold_min: int) -> None:
        self._db = db
        self._stale_threshold_min = stale_threshold_min

    def transition(
        self,
        call_id: int,
        to_status: CallStatus | str,
        *,
        actor: str,
        reason: str | None = None,
        step: LogStep | None = None,
        log_status: LogStatus | None = None,
        orchestrator_job_id: str | None = None,
        now: datetime | None = None,
    ) -> CallRecord:
        """`call_id` 건을 `to_status`로 전이하고 `processing_log`에 기록한다.

        actor: `robot`·`web` 등 호출 주체(로그 메시지에 남는다).
        step·log_status: 로그 단계·결과. 생략하면 전이 대상 상태로 정한다.
        없는(또는 소프트 삭제된) 건은 404, 허용되지 않은 전이는 `InvalidTransition`(409).
        """
        target = CallStatus(to_status)
        now = now or datetime.now(UTC)

        call = self._db.scalars(
            select(CallRecord)
            .where(CallRecord.id == call_id, CallRecord.deleted_at.is_(None))
            .with_for_update()
        ).one_or_none()
        if call is None:
            raise AppError(ErrorCode.NOT_FOUND)

        current = CallStatus(call.status)
        if not self._is_allowed(call, current, target, now):
            raise InvalidTransition(current, target)

        call.status = target
        call.status_changed_at = now
        if target is S.RETRY_REQUESTED:
            call.retry_count += 1

        self._db.add(
            ProcessingLog(
                call_id=call.id,
                step=step or self._default_step(current, target),
                status=log_status or self._default_log_status(target),
                message=self._message(actor, current, target, reason),
                orchestrator_job_id=orchestrator_job_id,
            )
        )
        self._db.flush()
        return call

    def _is_allowed(
        self, call: CallRecord, current: CallStatus, target: CallStatus, now: datetime
    ) -> bool:
        if target in _ALLOWED[current]:
            return True
        # 정체된 처리 중 건은 재처리 요청을 허용한다 (로봇이 멈춰 FAIL을 못 보낸 경우 포함).
        return target is S.RETRY_REQUESTED and is_stale(call, self._stale_threshold_min, now)

    @staticmethod
    def _default_step(current: CallStatus, target: CallStatus) -> LogStep:
        if target is S.FAILED:
            return _FAILED_STEP_BY_SOURCE[current]
        return _STEP_BY_TARGET[target]

    @staticmethod
    def _default_log_status(target: CallStatus) -> LogStatus:
        if target is S.FAILED:
            return LogStatus.FAIL
        if target is S.RETRY_REQUESTED:
            return LogStatus.RETRY
        return LogStatus.SUCCESS

    @staticmethod
    def _message(actor: str, current: CallStatus, target: CallStatus, reason: str | None) -> str:
        message = f"[{actor}] {current} -> {target}"
        return f"{message}: {reason}" if reason else message


def transition(
    db: Session,
    call_id: int,
    to_status: CallStatus | str,
    *,
    actor: str,
    reason: str | None = None,
) -> CallRecord:
    """B(W-03·W-05)가 쓰는 진입점. 정체 기준은 설정 `STALE_THRESHOLD_MIN`."""
    machine = CallStateMachine(db, stale_threshold_min=get_settings().stale_threshold_min)
    return machine.transition(call_id, to_status, actor=actor, reason=reason)
