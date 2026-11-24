from datetime import date

import pytest

from app.core.errors import AppError, ErrorCode
from app.services.stats_service import (
    MAX_TREND_BUCKETS,
    bucket_count,
    bucket_start,
    ensure_bucket_limit,
    iter_buckets,
)


@pytest.mark.parametrize(
    ("day", "granularity", "expected"),
    [
        (date(2026, 11, 25), "day", date(2026, 11, 25)),
        (date(2026, 11, 23), "week", date(2026, 11, 23)),  # 월요일
        (date(2026, 11, 29), "week", date(2026, 11, 23)),  # 일요일 → 그 주 월요일
        (date(2026, 1, 1), "week", date(2025, 12, 29)),  # 연도 경계
        (date(2026, 1, 31), "month", date(2026, 1, 1)),
    ],
)
def test_bucket_start(day: date, granularity: str, expected: date) -> None:
    assert bucket_start(day, granularity) == expected  # type: ignore[arg-type]


def test_iter_buckets_month_does_not_drift_and_crosses_year() -> None:
    months = list(iter_buckets(date(2026, 11, 1), date(2027, 3, 1), "month"))

    assert months == [
        date(2026, 11, 1),
        date(2026, 12, 1),
        date(2027, 1, 1),
        date(2027, 2, 1),
        date(2027, 3, 1),
    ]


def test_iter_buckets_day_and_week() -> None:
    assert list(iter_buckets(date(2026, 2, 27), date(2026, 3, 1), "day")) == [
        date(2026, 2, 27),
        date(2026, 2, 28),
        date(2026, 3, 1),
    ]
    assert list(iter_buckets(date(2026, 11, 16), date(2026, 11, 30), "week")) == [
        date(2026, 11, 16),
        date(2026, 11, 23),
        date(2026, 11, 30),
    ]


@pytest.mark.parametrize(
    ("first", "last", "granularity", "expected"),
    [
        (date(2026, 1, 1), date(2026, 1, 1), "day", 1),
        (date(2026, 1, 1), date(2026, 12, 31), "day", 365),
        (date(2026, 11, 16), date(2026, 11, 30), "week", 3),
        (date(2025, 11, 1), date(2026, 2, 1), "month", 4),
    ],
)
def test_bucket_count(first: date, last: date, granularity: str, expected: int) -> None:
    assert bucket_count(first, last, granularity) == expected  # type: ignore[arg-type]


def test_bucket_limit_allows_400_and_rejects_401() -> None:
    first = date(2026, 1, 1)
    ensure_bucket_limit(first, date(2027, 2, 4), "day")  # 400개

    with pytest.raises(AppError) as exc_info:
        ensure_bucket_limit(first, date(2027, 2, 5), "day")  # 401개

    assert MAX_TREND_BUCKETS == 400
    assert exc_info.value.code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.detail == {
        "errors": [
            {
                "loc": ["query", "from"],
                "msg": "기간이 너무 깁니다. 구간은 최대 400개입니다",
                "type": "range_too_large",
            }
        ]
    }
