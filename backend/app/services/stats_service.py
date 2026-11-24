"""통계 유스케이스 (W-10 추이·분류)."""

from collections.abc import Iterator
from datetime import date, timedelta

from app.core.errors import AppError, ErrorCode
from app.repositories.stats_repository import StatsRepository
from app.schemas.stats import (
    BreakdownBy,
    BreakdownItem,
    BreakdownResponse,
    CategoryCounts,
    Granularity,
    StatsPeriod,
    TrendPoint,
    TrendResponse,
)

MAX_TREND_BUCKETS = 400


def bucket_start(day: date, granularity: Granularity) -> date:
    """그날이 속한 구간의 시작일. 주는 월요일, 월은 1일."""
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return day


def bucket_count(first: date, last: date, granularity: Granularity) -> int:
    """구간 시작일 `first`~`last`(포함) 사이 구간 수."""
    if granularity == "month":
        return (last.year - first.year) * 12 + last.month - first.month + 1
    days = (last - first).days
    return days // 7 + 1 if granularity == "week" else days + 1


def iter_buckets(first: date, last: date, granularity: Granularity) -> Iterator[date]:
    current = first
    while current <= last:
        yield current
        if granularity == "month":
            # 1일에서 출발하므로 월말 밀림(01-31 → 02-28 → 03-28)이 없다.
            current = date(current.year + current.month // 12, current.month % 12 + 1, 1)
        else:
            current += timedelta(days=7 if granularity == "week" else 1)


def ensure_bucket_limit(first: date, last: date, granularity: Granularity) -> None:
    if bucket_count(first, last, granularity) > MAX_TREND_BUCKETS:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            detail={
                "errors": [
                    {
                        "loc": ["query", "from"],
                        "msg": f"기간이 너무 깁니다. 구간은 최대 {MAX_TREND_BUCKETS}개입니다",
                        "type": "range_too_large",
                    }
                ]
            },
        )


class StatsService:
    def __init__(self, repository: StatsRepository) -> None:
        self._repository = repository

    def trend(self, period: StatsPeriod, granularity: Granularity) -> TrendResponse:
        start = bucket_start(period.from_, granularity) if period.from_ else None
        end = bucket_start(period.to, granularity) if period.to else None
        if start and end:  # 닫힌 기간은 조회 전에 검사
            ensure_bucket_limit(start, end, granularity)
        counts = self._repository.count_by_period(period, granularity)
        if not counts:
            return TrendResponse(granularity=granularity, items=[])
        first = start or min(counts)
        last = end or max(counts)
        ensure_bucket_limit(first, last, granularity)  # 열린 기간은 데이터 범위로 검사
        items = [
            TrendPoint(period=day, count=counts.get(day, 0))
            for day in iter_buckets(first, last, granularity)
        ]
        return TrendResponse(granularity=granularity, items=items)

    def breakdown(self, period: StatsPeriod, by: BreakdownBy) -> BreakdownResponse:
        rows = sorted(
            self._repository.count_by_dimension(period, by),
            key=lambda row: (row.name is None, -row.count, row.name or ""),
        )
        items = [
            BreakdownItem(
                name=row.name,
                count=row.count,
                by_category=CategoryCounts.model_validate(
                    {code.value: n for code, n in row.by_category.items()}
                ),
            )
            for row in rows
        ]
        return BreakdownResponse(by=by, items=items)
