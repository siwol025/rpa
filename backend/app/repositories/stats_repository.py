"""통계 집계 쿼리. 조건(삭제 제외·기간)은 목록과 같은 `filter_conditions`를 쓴다."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    ColumnElement,
    DateTime,
    Label,
    and_,
    case,
    func,
    literal_column,
    null,
    select,
)
from sqlalchemy.orm import Session

from app.models import Analysis, CallRecord
from app.repositories.call_repository import filter_conditions
from app.schemas.call import CATEGORY_DB_VALUES, CallStatus, Category
from app.schemas.stats import BreakdownBy, CategoryCounts, Granularity, StatsPeriod, StatsSummary
from app.services.stale_detection import stale_condition

# date_trunc 단위. SQL에 상수로 들어가므로 이 허용 목록의 값만 쓴다.
_TRUNC_UNITS: dict[Granularity, str] = {"day": "day", "week": "week", "month": "month"}
# '+09:00' 문자열은 POSIX 해석(UTC-9)이라 쓰지 않는다. 세션 TimeZone에도 의존하지 않는다.
_KST_ZONE = "Asia/Seoul"

_DIMENSION_COLUMNS = {
    "agent": CallRecord.agent_name,
    "client": CallRecord.client_company,
}


@dataclass(frozen=True)
class DimensionCount:
    name: str | None
    count: int
    by_category: dict[Category, int]


def period_column(granularity: Granularity) -> Label[Any]:
    """KST 기준 구간 시작 시각(naive). SELECT·GROUP BY에 이 객체 하나를 같이 쓴다."""
    local = func.timezone(literal_column(f"'{_KST_ZONE}'"), CallRecord.call_datetime)
    unit: ColumnElement[str] = literal_column(f"'{_TRUNC_UNITS[granularity]}'")
    return func.date_trunc(unit, local, type_=DateTime()).label("period")


def dimension_column(by: BreakdownBy) -> Label[Any]:
    """담당자·고객사 이름. 공백만 있는 값은 NULL로 합치고, 나머지는 저장 값 그대로 쓴다."""
    column = _DIMENSION_COLUMNS[by]
    return case((func.btrim(column) == "", null()), else_=column).label("name")


class StatsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def count_by_period(self, period: StatsPeriod, granularity: Granularity) -> dict[date, int]:
        """값이 있는 구간만 `{구간 시작일: 건수}`. 통화 일시가 없는 건은 제외."""
        bucket = period_column(granularity)
        stmt = (
            select(bucket, func.count())
            .select_from(CallRecord)
            .where(*filter_conditions(period.call_filter()), CallRecord.call_datetime.is_not(None))
            .group_by(bucket)
        )
        return {start.date(): count for start, count in self._session.execute(stmt)}

    def count_by_dimension(self, period: StatsPeriod, by: BreakdownBy) -> list[DimensionCount]:
        name = dimension_column(by)
        by_category = [
            func.count().filter(Analysis.category == CATEGORY_DB_VALUES[code]) for code in Category
        ]
        stmt = (
            select(name, func.count(), *by_category)
            .select_from(CallRecord)
            .outerjoin(Analysis, Analysis.call_id == CallRecord.id)
            .where(*filter_conditions(period.call_filter()))
            .group_by(name)
        )
        return [
            DimensionCount(
                name=row[0],
                count=row[1],
                by_category=dict(zip(Category, row[2:], strict=True)),
            )
            for row in self._session.execute(stmt)
        ]

    def summary(
        self, period: StatsPeriod, *, stale_threshold_min: int, now: datetime | None = None
    ) -> StatsSummary:
        """쿼리 1회. 기간은 `total`·`by_category`에만 적용한다(삭제 제외는 전체 공통)."""
        in_period = and_(*filter_conditions(period.call_filter()))
        by_category = [
            func.count().filter(in_period, Analysis.category == CATEGORY_DB_VALUES[code])
            for code in Category
        ]
        stmt = (
            select(
                func.count().filter(in_period),
                func.count().filter(Analysis.action_status == "OPEN"),
                func.count().filter(CallRecord.status == CallStatus.NEEDS_REVIEW),
                func.count().filter(CallRecord.metadata_incomplete.is_(True)),
                func.count().filter(CallRecord.status == CallStatus.FAILED),
                func.count().filter(stale_condition(stale_threshold_min, now)),
                *by_category,
            )
            .select_from(CallRecord)
            .outerjoin(Analysis, Analysis.call_id == CallRecord.id)
            .where(CallRecord.deleted_at.is_(None))
        )
        row = self._session.execute(stmt).one()
        total, action_open, needs_review, metadata_incomplete, failed, stale = row[:6]
        return StatsSummary(
            total=total,
            by_category=CategoryCounts.model_validate(
                dict(zip((code.value for code in Category), row[6:], strict=True))
            ),
            action_open=action_open,
            needs_review=needs_review,
            metadata_incomplete=metadata_incomplete,
            failed=failed,
            stale=stale,
        )
