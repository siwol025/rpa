"""상담 조회 쿼리. 소프트 삭제된 건은 항상 제외한다 (architecture.md §3.1)."""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Row, Select, UnaryExpression, func, or_, select
from sqlalchemy.orm import Session

from app.models import Analysis, CallRecord, Transcript
from app.schemas.call import CATEGORY_DB_VALUES, CallListQuery, CallSort
from app.schemas.common import KST

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


def filter_conditions(query: CallListQuery) -> list[ColumnElement[bool]]:
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
    if keyword := query.keyword:
        conditions.append(
            or_(
                Analysis.question_summary.icontains(keyword, autoescape=True),
                Analysis.action_summary.icontains(keyword, autoescape=True),
                Transcript.corrected_text.icontains(keyword, autoescape=True),
            )
        )
    return conditions


def _filtered[T: tuple[Any, ...]](stmt: Select[T], query: CallListQuery) -> Select[T]:
    # transcript·analysis는 call_id UNIQUE라 JOIN해도 행이 늘지 않는다 (COUNT 정확, DISTINCT 없음).
    stmt = stmt.outerjoin(Analysis, Analysis.call_id == CallRecord.id)
    if query.keyword:
        stmt = stmt.outerjoin(Transcript, Transcript.call_id == CallRecord.id)
    return stmt.where(*filter_conditions(query))


class CallRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_calls(self, query: CallListQuery, *, offset: int, limit: int) -> Sequence[ListRow]:
        stmt = select(
            CallRecord, Analysis.category, Analysis.question_summary, Analysis.action_status
        ).select_from(CallRecord)
        stmt = _filtered(stmt, query).order_by(*order_by_clause(query.sort))
        result = self._session.execute(stmt.offset(offset).limit(limit))
        # outer join이라 분석 컬럼은 None일 수 있다 (매핑 타입보다 넓은 ListRow로 반환).
        return result.all()  # type: ignore[return-value]

    def count_calls(self, query: CallListQuery) -> int:
        stmt = _filtered(select(func.count()).select_from(CallRecord), query)
        return self._session.execute(stmt).scalar_one()
