"""상담 조회·수정 쿼리. 소프트 삭제된 건은 항상 제외한다 (architecture.md §3.1)."""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Row, Select, UnaryExpression, func, not_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Analysis, CallRecord, EditHistory, ProcessingLog, Transcript
from app.schemas.call import CATEGORY_DB_VALUES, CallListQuery, CallSort
from app.schemas.common import KST
from app.services.stale_detection import stale_condition

ListRow = Row[tuple[CallRecord, str | None, str | None, str | None]]

_SORT_COLUMNS = {
    "call_datetime": CallRecord.call_datetime,
    "created_at": CallRecord.created_at,
    "status_changed_at": CallRecord.status_changed_at,
}


def kst_day_start(day: date) -> datetime:
    """KST 기준 그날 00:00 (aware)."""
    return datetime(day.year, day.month, day.day, tzinfo=KST)


def order_by_clause(sort: CallSort) -> list[UnaryExpression[Any]]:
    """`-`는 내림차순. `call_datetime`은 방향과 무관하게 NULLS LAST, 끝에 같은 방향 id."""
    desc = sort.startswith("-")
    field = sort.removeprefix("-")
    column = _SORT_COLUMNS[field]
    primary = column.desc() if desc else column.asc()
    if field == "call_datetime":
        primary = primary.nulls_last()
    return [primary, CallRecord.id.desc() if desc else CallRecord.id.asc()]


def filter_conditions(
    query: CallListQuery,
    *,
    stale_threshold_min: int | None = None,
    now: datetime | None = None,
) -> list[ColumnElement[bool]]:
    """`stale` 필터를 쓰려면 정체 기준(분)이 필요하다. `now`는 `is_stale` 계산과 같은 시각."""
    conditions: list[ColumnElement[bool]] = [CallRecord.deleted_at.is_(None)]
    if query.from_:
        conditions.append(CallRecord.call_datetime >= kst_day_start(query.from_))
    if query.to:
        conditions.append(CallRecord.call_datetime < kst_day_start(query.to + timedelta(days=1)))
    if query.category:
        db_values = [CATEGORY_DB_VALUES[code] for code in query.category]
        conditions.append(Analysis.category.in_(db_values))
    if query.agent and query.agent.strip():
        conditions.append(CallRecord.agent_name == query.agent)
    if query.client and query.client.strip():
        conditions.append(CallRecord.client_company == query.client)
    if query.status:
        conditions.append(CallRecord.status.in_(query.status))
    if query.metadata_incomplete is not None:
        conditions.append(CallRecord.metadata_incomplete.is_(query.metadata_incomplete))
    if query.stale is not None:
        if stale_threshold_min is None:
            raise ValueError("stale 필터에는 stale_threshold_min이 필요합니다")
        stale = stale_condition(stale_threshold_min, now)
        conditions.append(stale if query.stale else not_(stale))
    if keyword := query.keyword:
        conditions.append(
            or_(
                Analysis.question_summary.icontains(keyword, autoescape=True),
                Analysis.action_summary.icontains(keyword, autoescape=True),
                Transcript.corrected_text.icontains(keyword, autoescape=True),
            )
        )
    return conditions


def _filtered[T: tuple[Any, ...]](
    stmt: Select[T], query: CallListQuery, stale_threshold_min: int | None, now: datetime | None
) -> Select[T]:
    # transcript·analysis는 call_id UNIQUE라 JOIN해도 행이 늘지 않는다 (COUNT 정확, DISTINCT 없음).
    stmt = stmt.outerjoin(Analysis, Analysis.call_id == CallRecord.id)
    if query.keyword:
        stmt = stmt.outerjoin(Transcript, Transcript.call_id == CallRecord.id)
    return stmt.where(*filter_conditions(query, stale_threshold_min=stale_threshold_min, now=now))


class CallRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_calls(
        self,
        query: CallListQuery,
        *,
        offset: int,
        limit: int,
        stale_threshold_min: int | None = None,
        now: datetime | None = None,
    ) -> Sequence[ListRow]:
        stmt = select(
            CallRecord, Analysis.category, Analysis.question_summary, Analysis.action_status
        ).select_from(CallRecord)
        stmt = _filtered(stmt, query, stale_threshold_min, now).order_by(
            *order_by_clause(query.sort)
        )
        result = self._session.execute(stmt.offset(offset).limit(limit))
        # outer join이라 분석 컬럼은 None일 수 있다 (매핑 타입보다 넓은 ListRow로 반환).
        return result.all()  # type: ignore[return-value]

    def count_calls(
        self,
        query: CallListQuery,
        *,
        stale_threshold_min: int | None = None,
        now: datetime | None = None,
    ) -> int:
        stmt = _filtered(
            select(func.count()).select_from(CallRecord), query, stale_threshold_min, now
        )
        return self._session.execute(stmt).scalar_one()

    def get_call(self, call_id: int) -> CallRecord | None:
        """삭제되지 않은 건 + transcript·analysis(1:0..1)를 한 번에 읽는다."""
        stmt = (
            select(CallRecord)
            .options(joinedload(CallRecord.transcript), joinedload(CallRecord.analysis))
            .where(CallRecord.id == call_id, CallRecord.deleted_at.is_(None))
        )
        return self._session.scalars(stmt).one_or_none()

    def lock_call(self, call_id: int) -> CallRecord | None:
        """삭제되지 않은 건을 행 잠금(`FOR UPDATE`)으로 읽는다. 트랜잭션 끝까지 잠금이 유지된다.

        상태 머신·로봇 서비스의 잠금 조회와 같은 SQL이다. 관계를 함께 읽지 않는다
        (PostgreSQL은 OUTER JOIN의 NULL 가능 쪽에 FOR UPDATE 불가).
        """
        stmt = (
            select(CallRecord)
            .where(CallRecord.id == call_id, CallRecord.deleted_at.is_(None))
            .with_for_update()
        )
        return self._session.scalars(stmt).one_or_none()

    def add_edit_history(
        self,
        call_id: int,
        field: str,
        before: str | None,
        after: str | None,
        *,
        editor: str | None,
    ) -> None:
        """수정 이력 1행. `edited_at`은 DB 기본값(now())."""
        self._session.add(
            EditHistory(
                call_id=call_id, field=field, before_val=before, after_val=after, editor=editor
            )
        )

    def list_logs(self, call_id: int) -> Sequence[ProcessingLog]:
        # CallRecord.logs 관계에는 순서가 없어 별도 쿼리로 처리 순서를 보장한다.
        stmt = (
            select(ProcessingLog)
            .where(ProcessingLog.call_id == call_id)
            .order_by(ProcessingLog.created_at.asc(), ProcessingLog.id.asc())
        )
        return self._session.scalars(stmt).all()
