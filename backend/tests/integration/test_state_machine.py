"""R-02 상태 머신 (실제 PostgreSQL)."""

from datetime import UTC, datetime, timedelta
from itertools import product

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import ProcessingLog
from app.schemas.call import CallStatus, LogStatus, LogStep
from app.services.state_machine import (
    _ALLOWED,
    CallStateMachine,
    InvalidTransition,
    is_stale,
    transition,
)
from tests.factories import make_call_record

pytestmark = pytest.mark.integration

S = CallStatus
THRESHOLD = 30
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)

ALLOWED_PAIRS = [(src, dst) for src, dsts in _ALLOWED.items() for dst in sorted(dsts)]
# 전이표에 없는 조합. 정체가 아닌 건에서는 처리 중 상태의 RETRY_REQUESTED 요청도 여기에 든다.
DENIED_PAIRS = [
    (src, dst) for src, dst in product(CallStatus, CallStatus) if dst not in _ALLOWED[src]
]


@pytest.fixture
def machine(db: Session) -> CallStateMachine:
    return CallStateMachine(db, stale_threshold_min=THRESHOLD)


def _logs(db: Session, call_id: int) -> list[ProcessingLog]:
    return list(
        db.scalars(
            select(ProcessingLog).where(ProcessingLog.call_id == call_id).order_by(ProcessingLog.id)
        )
    )


@pytest.mark.parametrize(("src", "dst"), ALLOWED_PAIRS)
def test_allowed_transition_updates_status_and_logs(
    db: Session, machine: CallStateMachine, src: CallStatus, dst: CallStatus
) -> None:
    long_ago = NOW - timedelta(hours=1)
    call = make_call_record(db, status=src, status_changed_at=long_ago)

    result = machine.transition(call.id, dst, actor="robot", now=NOW)

    assert result.status == dst
    assert result.status_changed_at == NOW
    logs = _logs(db, call.id)
    assert len(logs) == 1
    assert f"{src} -> {dst}" in (logs[0].message or "")
    assert logs[0].message is not None
    assert logs[0].message.startswith("[robot]")


@pytest.mark.parametrize(("src", "dst"), DENIED_PAIRS)
def test_denied_transition_raises_409_with_current_status(
    db: Session, machine: CallStateMachine, src: CallStatus, dst: CallStatus
) -> None:
    # 방금 바뀐 건이라 정체가 아니다.
    call = make_call_record(db, status=src, status_changed_at=NOW)

    with pytest.raises(InvalidTransition) as exc:
        machine.transition(call.id, dst, actor="robot", now=NOW)

    assert exc.value.code is ErrorCode.INVALID_STATE_TRANSITION
    assert exc.value.detail == {"current_status": src, "requested_status": dst}
    db.refresh(call)
    assert call.status == src  # 거절되면 아무것도 바뀌지 않는다
    assert call.status_changed_at == NOW
    assert _logs(db, call.id) == []


@pytest.mark.parametrize("src", [S.REGISTERED, S.QUEUED, S.STT_DONE])
def test_stale_processing_call_can_be_retried(
    db: Session, machine: CallStateMachine, src: CallStatus
) -> None:
    call = make_call_record(db, status=src, status_changed_at=NOW - timedelta(minutes=31))

    result = machine.transition(call.id, S.RETRY_REQUESTED, actor="web", now=NOW)

    assert result.status is S.RETRY_REQUESTED
    assert result.retry_count == 1
    assert _logs(db, call.id)[0].step == LogStep.RETRY
    assert _logs(db, call.id)[0].status == LogStatus.RETRY


def test_stale_retry_requested_call_cannot_be_requested_again(
    db: Session, machine: CallStateMachine
) -> None:
    call = make_call_record(
        db, status=S.RETRY_REQUESTED, status_changed_at=NOW - timedelta(hours=3)
    )

    with pytest.raises(InvalidTransition) as exc:
        machine.transition(call.id, S.RETRY_REQUESTED, actor="web", now=NOW)

    assert exc.value.current_status == S.RETRY_REQUESTED
    assert call.retry_count == 0
    assert is_stale(call, THRESHOLD, NOW) is True  # 정체 감지에는 계속 잡힌다


@pytest.mark.parametrize("src", [S.REGISTERED, S.QUEUED, S.STT_DONE, S.RETRY_REQUESTED])
def test_not_stale_processing_call_cannot_be_retried(
    db: Session, machine: CallStateMachine, src: CallStatus
) -> None:
    call = make_call_record(db, status=src, status_changed_at=NOW - timedelta(minutes=29))

    with pytest.raises(InvalidTransition) as exc:
        machine.transition(call.id, S.RETRY_REQUESTED, actor="web", now=NOW)

    assert exc.value.current_status == src


def test_stale_boundary_is_exclusive(db: Session) -> None:
    exactly = make_call_record(
        db, status=S.QUEUED, status_changed_at=NOW - timedelta(minutes=THRESHOLD)
    )
    over = make_call_record(
        db, status=S.QUEUED, status_changed_at=NOW - timedelta(minutes=THRESHOLD, seconds=1)
    )

    assert is_stale(exactly, THRESHOLD, NOW) is False
    assert is_stale(over, THRESHOLD, NOW) is True


@pytest.mark.parametrize("terminal", [S.STORED, S.NEEDS_REVIEW, S.FAILED])
def test_finished_call_is_never_stale(db: Session, terminal: CallStatus) -> None:
    call = make_call_record(db, status=terminal, status_changed_at=NOW - timedelta(days=3))

    assert is_stale(call, THRESHOLD, NOW) is False


def test_retry_count_accumulates(db: Session, machine: CallStateMachine) -> None:
    call = make_call_record(db, status=S.FAILED, status_changed_at=NOW)

    machine.transition(call.id, S.RETRY_REQUESTED, actor="web", now=NOW)
    machine.transition(call.id, S.QUEUED, actor="robot", now=NOW)
    machine.transition(call.id, S.FAILED, actor="robot", now=NOW)
    machine.transition(call.id, S.RETRY_REQUESTED, actor="web", now=NOW)

    assert call.retry_count == 2


def test_full_happy_path_leaves_one_log_per_step(db: Session, machine: CallStateMachine) -> None:
    call = make_call_record(db)

    for target in (S.QUEUED, S.STT_DONE, S.STORED):
        machine.transition(call.id, target, actor="robot", now=NOW)

    assert [(log.step, log.status) for log in _logs(db, call.id)] == [
        ("QUEUE", "SUCCESS"),
        ("STT", "SUCCESS"),
        ("STORE", "SUCCESS"),
    ]


@pytest.mark.parametrize(
    ("src", "expected_step"),
    [(S.REGISTERED, "REGISTER"), (S.QUEUED, "STT"), (S.STT_DONE, "GENAI")],
)
def test_failure_log_step_follows_previous_status(
    db: Session, machine: CallStateMachine, src: CallStatus, expected_step: str
) -> None:
    call = make_call_record(db, status=src, status_changed_at=NOW)

    machine.transition(call.id, S.FAILED, actor="robot", reason="timeout", now=NOW)

    log = _logs(db, call.id)[0]
    assert (log.step, log.status) == (expected_step, "FAIL")
    assert log.message is not None
    assert log.message.endswith(": timeout")


def test_caller_can_override_log_step_and_status(db: Session, machine: CallStateMachine) -> None:
    call = make_call_record(db, status=S.STT_DONE, status_changed_at=NOW)

    machine.transition(
        call.id, S.FAILED, actor="robot", step=LogStep.EXCEL, log_status=LogStatus.FAIL, now=NOW
    )

    assert _logs(db, call.id)[0].step == "EXCEL"


def test_unknown_call_is_404(machine: CallStateMachine) -> None:
    with pytest.raises(AppError) as exc:
        machine.transition(999_999, S.QUEUED, actor="robot")

    assert exc.value.code is ErrorCode.NOT_FOUND


def test_soft_deleted_call_is_404(db: Session, machine: CallStateMachine) -> None:
    call = make_call_record(db, deleted_at=NOW)

    with pytest.raises(AppError) as exc:
        machine.transition(call.id, S.QUEUED, actor="robot")

    assert exc.value.code is ErrorCode.NOT_FOUND


def test_transition_locks_the_row(db: Session, machine: CallStateMachine) -> None:
    call = make_call_record(db)
    statements: list[str] = []

    def capture(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        machine.transition(call.id, S.QUEUED, actor="robot", now=NOW)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert any("FOR UPDATE" in statement for statement in statements)


def test_module_function_uses_settings_threshold(db: Session) -> None:
    call = make_call_record(db, status=S.QUEUED)

    result = transition(db, call.id, "STT_DONE", actor="robot", reason="ok")

    assert result.status is S.STT_DONE
