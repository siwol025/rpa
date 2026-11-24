from datetime import date
from typing import cast

import pytest

from app.core.errors import AppError
from app.repositories.stats_repository import DimensionCount, StatsRepository
from app.schemas.call import Category
from app.schemas.stats import BreakdownBy, Granularity, StatsPeriod
from app.services.stats_service import StatsService


class FakeStatsRepository:
    def __init__(
        self,
        periods: dict[date, int] | None = None,
        dimensions: list[DimensionCount] | None = None,
    ) -> None:
        self.periods = periods or {}
        self.dimensions = dimensions or []
        self.calls: list[tuple[str, StatsPeriod, str]] = []

    def count_by_period(self, period: StatsPeriod, granularity: Granularity) -> dict[date, int]:
        self.calls.append(("period", period, granularity))
        return self.periods

    def count_by_dimension(self, period: StatsPeriod, by: BreakdownBy) -> list[DimensionCount]:
        self.calls.append(("dimension", period, by))
        return self.dimensions


def _service(repo: FakeStatsRepository) -> StatsService:
    return StatsService(cast(StatsRepository, repo))


def _row(name: str | None, count: int, **by_category: int) -> DimensionCount:
    counts = {code: by_category.get(code.value, 0) for code in Category}
    return DimensionCount(name=name, count=count, by_category=counts)


def test_trend_fills_zero_buckets_across_requested_range() -> None:
    repo = FakeStatsRepository({date(2026, 11, 2): 3})
    period = StatsPeriod(from_=date(2026, 11, 1), to=date(2026, 11, 4))

    body = _service(repo).trend(period, "day").model_dump(mode="json")

    assert body["granularity"] == "day"
    assert body["items"] == [
        {"period": "2026-11-01", "count": 0},
        {"period": "2026-11-02", "count": 3},
        {"period": "2026-11-03", "count": 0},
        {"period": "2026-11-04", "count": 0},
    ]
    assert repo.calls == [("period", period, "day")]


def test_trend_partial_week_starts_on_monday() -> None:
    repo = FakeStatsRepository({date(2026, 11, 23): 2})
    period = StatsPeriod(from_=date(2026, 11, 18), to=date(2026, 11, 25))  # 수 ~ 다음 주 수

    items = _service(repo).trend(period, "week").items

    assert [(i.period, i.count) for i in items] == [
        (date(2026, 11, 16), 0),
        (date(2026, 11, 23), 2),
    ]


def test_trend_open_range_uses_first_and_last_data_bucket() -> None:
    repo = FakeStatsRepository({date(2026, 9, 1): 1, date(2026, 11, 1): 4})

    items = _service(repo).trend(StatsPeriod(), "month").items

    assert [(i.period, i.count) for i in items] == [
        (date(2026, 9, 1), 1),
        (date(2026, 10, 1), 0),
        (date(2026, 11, 1), 4),
    ]


def test_trend_from_only_fills_from_requested_start_to_last_data_bucket() -> None:
    repo = FakeStatsRepository({date(2026, 11, 23): 1})

    items = _service(repo).trend(StatsPeriod(from_=date(2026, 11, 18)), "week").items

    assert [(i.period, i.count) for i in items] == [
        (date(2026, 11, 16), 0),
        (date(2026, 11, 23), 1),
    ]


def test_trend_without_data_returns_empty_items() -> None:
    period = StatsPeriod(from_=date(2026, 11, 1), to=date(2026, 11, 30))

    body = _service(FakeStatsRepository()).trend(period, "day")

    assert body.items == []


def test_trend_closed_range_too_large_is_rejected_before_query() -> None:
    repo = FakeStatsRepository()
    period = StatsPeriod(from_=date(2026, 1, 1), to=date(2027, 2, 5))  # 401일

    with pytest.raises(AppError) as exc_info:
        _service(repo).trend(period, "day")

    assert exc_info.value.detail is not None
    assert exc_info.value.detail["errors"][0]["type"] == "range_too_large"
    assert repo.calls == []
    _service(repo).trend(period, "week")  # 같은 기간도 주 단위면 허용


def test_trend_open_range_too_large_is_rejected_after_query() -> None:
    repo = FakeStatsRepository({date(2020, 1, 1): 1, date(2026, 11, 1): 1})

    with pytest.raises(AppError):
        _service(repo).trend(StatsPeriod(to=date(2026, 11, 30)), "day")
    assert len(repo.calls) == 1


def test_breakdown_sorts_by_count_then_name_with_null_last() -> None:
    repo = FakeStatsRepository(
        dimensions=[
            _row(None, 9),
            _row("나상사", 2),
            _row("가상사", 2),
            _row("다상사", 5, COMPLAINT=3, INQUIRY=1),
        ]
    )

    body = _service(repo).breakdown(StatsPeriod(), "client").model_dump(mode="json")

    assert body["by"] == "client"
    assert [(i["name"], i["count"]) for i in body["items"]] == [
        ("다상사", 5),
        ("가상사", 2),
        ("나상사", 2),
        (None, 9),
    ]
    assert body["items"][0]["by_category"] == {
        "INQUIRY": 1,
        "COMPLAINT": 3,
        "SUGGESTION": 0,
        "EDUCATION": 0,
        "ETC": 0,
    }


def test_breakdown_without_data_returns_empty_items() -> None:
    assert _service(FakeStatsRepository()).breakdown(StatsPeriod(), "agent").items == []
