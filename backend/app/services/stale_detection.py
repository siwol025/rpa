"""정체 감지 (R-11): 처리 중 상태로 기준 시간을 넘게 머문 건을 조회·집계한다.

정체 기준은 상태 머신의 `is_stale`과 같다. 처리 중 상태(`STALE_ELIGIBLE`)이고
`status_changed_at`이 `threshold_min`분보다 오래된 건이며, 삭제된 건은 제외한다.
읽기 전용이라 commit하지 않는다.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import Session

from app.models import CallRecord
from app.schemas.call import CallStatus
from app.services.state_machine import STALE_ELIGIBLE


def stale_condition(threshold_min: int, now: datetime | None = None) -> ColumnElement[bool]:
    """정체 건의 WHERE 조건. 목록 필터(W-01)·통계(W-09)가 다른 조건과 합쳐 쓴다."""
    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=threshold_min)
    return and_(
        CallRecord.deleted_at.is_(None),
        CallRecord.status.in_(STALE_ELIGIBLE),
        CallRecord.status_changed_at < cutoff,
    )


def list_stale_calls(
    db: Session,
    threshold_min: int,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> Sequence[CallRecord]:
    """정체 건을 오래된 순으로 돌려준다."""
    stmt = (
        select(CallRecord)
        .where(stale_condition(threshold_min, now))
        .order_by(CallRecord.status_changed_at, CallRecord.id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return db.scalars(stmt).all()


def count_stale_calls(db: Session, threshold_min: int, *, now: datetime | None = None) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(CallRecord).where(stale_condition(threshold_min, now))
        )
        or 0
    )


def count_stale_by_status(
    db: Session, threshold_min: int, *, now: datetime | None = None
) -> dict[CallStatus, int]:
    """상태별 정체 건수. 정체 건이 없는 상태도 0으로 포함한다."""
    rows = db.execute(
        select(CallRecord.status, func.count())
        .where(stale_condition(threshold_min, now))
        .group_by(CallRecord.status)
    ).all()
    counts = dict.fromkeys(sorted(STALE_ELIGIBLE), 0)
    counts.update({CallStatus(status): count for status, count in rows})
    return counts
