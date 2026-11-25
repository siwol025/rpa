"""R-11 정체 감지 조회·집계 (실제 PostgreSQL)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models import CallRecord
from app.schemas.call import CallStatus
from app.services.stale_detection import (
    count_stale_by_status,
    count_stale_calls,
    list_stale_calls,
    stale_condition,
)
from app.services.state_machine import STALE_ELIGIBLE, CallStateMachine, is_stale
from tests.factories import make_call_record

pytestmark = pytest.mark.integration

S = CallStatus
THRESHOLD = 30
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def aged(db: Session, status: S, minutes: float, **fields: object) -> CallRecord:
    return make_call_record(
        db, status=status, status_changed_at=NOW - timedelta(minutes=minutes), **fields
    )


@pytest.mark.parametrize("status", sorted(STALE_ELIGIBLE))
def test_processing_call_past_threshold_is_stale(db: Session, status: S) -> None:
    call = aged(db, status, THRESHOLD + 1)

    assert list_stale_calls(db, THRESHOLD, now=NOW) == [call]
    assert count_stale_calls(db, THRESHOLD, now=NOW) == 1


@pytest.mark.parametrize("status", sorted(STALE_ELIGIBLE))
def test_processing_call_within_threshold_is_not_stale(db: Session, status: S) -> None:
    aged(db, status, THRESHOLD - 1)

    assert list_stale_calls(db, THRESHOLD, now=NOW) == []
    assert count_stale_calls(db, THRESHOLD, now=NOW) == 0


def test_exactly_at_threshold_is_not_stale(db: Session) -> None:
    aged(db, S.QUEUED, THRESHOLD)

    assert count_stale_calls(db, THRESHOLD, now=NOW) == 0


@pytest.mark.parametrize("status", [S.STORED, S.NEEDS_REVIEW, S.FAILED])
def test_finished_calls_are_never_stale(db: Session, status: S) -> None:
    aged(db, status, 24 * 60)

    assert count_stale_calls(db, THRESHOLD, now=NOW) == 0


def test_soft_deleted_calls_are_excluded(db: Session) -> None:
    aged(db, S.QUEUED, 120, deleted_at=NOW)

    assert count_stale_calls(db, THRESHOLD, now=NOW) == 0


def test_list_is_oldest_first_and_limit_applies(db: Session) -> None:
    newer = aged(db, S.QUEUED, 60)
    oldest = aged(db, S.REGISTERED, 300)
    middle = aged(db, S.STT_DONE, 120)

    assert list_stale_calls(db, THRESHOLD, now=NOW) == [oldest, middle, newer]
    assert list_stale_calls(db, THRESHOLD, now=NOW, limit=2) == [oldest, middle]


def test_count_by_status_includes_zero_for_missing_statuses(db: Session) -> None:
    aged(db, S.QUEUED, 60)
    aged(db, S.QUEUED, 90)
    aged(db, S.REGISTERED, 45)

    assert count_stale_by_status(db, THRESHOLD, now=NOW) == {
        S.REGISTERED: 1,
        S.QUEUED: 2,
        S.STT_DONE: 0,
        S.RETRY_REQUESTED: 0,
    }


def test_detection_matches_state_machine_rule(db: Session) -> None:
    calls = [aged(db, status, minutes) for status in S for minutes in (10, 30, 31, 600)]

    detected = {call.id for call in list_stale_calls(db, THRESHOLD, now=NOW)}

    assert detected == {call.id for call in calls if is_stale(call, THRESHOLD, NOW)}


def test_condition_combines_with_other_filters(db: Session) -> None:
    from sqlalchemy import select

    queued = aged(db, S.QUEUED, 60)
    aged(db, S.REGISTERED, 60)

    found = db.scalars(
        select(CallRecord).where(stale_condition(THRESHOLD, NOW), CallRecord.status == S.QUEUED)
    ).all()

    assert found == [queued]


def test_every_listed_call_can_be_requested_for_retry(db: Session) -> None:
    aged(db, S.REGISTERED, 60)
    aged(db, S.QUEUED, 60)
    aged(db, S.STT_DONE, 60)
    machine = CallStateMachine(db, stale_threshold_min=THRESHOLD)

    for call in list_stale_calls(db, THRESHOLD, now=NOW):
        machine.transition(call.id, S.RETRY_REQUESTED, actor="web", now=NOW)

    assert count_stale_by_status(db, THRESHOLD, now=NOW)[S.QUEUED] == 0
    assert count_stale_calls(db, THRESHOLD, now=NOW) == 0  # RETRY_REQUESTED로 바뀌며 시간이 초기화
