from datetime import date

import pytest

from app.core.errors import AppError
from app.schemas.call import CallListQuery, Category
from app.schemas.stats import (
    BreakdownItem,
    CategoryCounts,
    StatsPeriod,
    TrendPoint,
    TrendResponse,
)


def test_period_reuses_call_list_date_rules() -> None:
    period = StatsPeriod(from_=date(2026, 11, 1), to=date(2026, 11, 23))

    assert period.call_filter() == CallListQuery(from_=date(2026, 11, 1), to=date(2026, 11, 23))


def test_period_from_after_to_raises_date_range() -> None:
    with pytest.raises(AppError) as exc_info:
        StatsPeriod(from_=date(2026, 11, 2), to=date(2026, 11, 1))

    assert exc_info.value.detail is not None
    assert exc_info.value.detail["errors"][0]["type"] == "date_range"


def test_category_counts_has_every_category_code() -> None:
    assert set(CategoryCounts.model_fields) == {code.value for code in Category}


def test_trend_period_serializes_as_date() -> None:
    body = TrendResponse(
        granularity="week", items=[TrendPoint(period=date(2026, 11, 23), count=3)]
    ).model_dump(mode="json")

    assert body == {"granularity": "week", "items": [{"period": "2026-11-23", "count": 3}]}


def test_breakdown_item_allows_null_name() -> None:
    zero = dict.fromkeys(CategoryCounts.model_fields, 0)
    item = BreakdownItem(name=None, count=2, by_category=CategoryCounts.model_validate(zero))

    assert item.model_dump(mode="json") == {"name": None, "count": 2, "by_category": zero}
