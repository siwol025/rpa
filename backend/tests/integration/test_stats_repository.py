from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.repositories.stats_repository import StatsRepository
from app.schemas.call import Category
from app.schemas.common import KST
from app.schemas.stats import StatsPeriod, StatsSummary
from tests.integration.factories import make_analysis, make_call

pytestmark = pytest.mark.integration


def _kst(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=KST)


def test_day_bucket_uses_kst_not_session_timezone(db: Session) -> None:
    # 00:30 KST = 전날 15:30 UTC. 세션 TimeZone(UTC)으로 자르면 전날로 묶인다.
    make_call(db, call_datetime=_kst(2026, 11, 22, 23, 59, 59))
    make_call(db, call_datetime=_kst(2026, 11, 23, 0, 0))
    make_call(db, call_datetime=_kst(2026, 11, 23, 0, 30))

    counts = StatsRepository(db).count_by_period(StatsPeriod(), "day")

    assert counts == {date(2026, 11, 22): 1, date(2026, 11, 23): 2}


def test_week_bucket_starts_monday_kst(db: Session) -> None:
    make_call(db, call_datetime=_kst(2026, 11, 29, 23, 59))  # 일요일
    make_call(db, call_datetime=_kst(2026, 11, 30, 0, 0))  # 월요일

    counts = StatsRepository(db).count_by_period(StatsPeriod(), "week")

    assert counts == {date(2026, 11, 23): 1, date(2026, 11, 30): 1}


def test_month_bucket_boundary_kst(db: Session) -> None:
    make_call(db, call_datetime=_kst(2026, 11, 30, 23, 59))
    make_call(db, call_datetime=_kst(2026, 12, 1, 0, 0))

    counts = StatsRepository(db).count_by_period(StatsPeriod(), "month")

    assert counts == {date(2026, 11, 1): 1, date(2026, 12, 1): 1}


def test_trend_excludes_deleted_and_missing_datetime_counts_all_statuses(
    db: Session,
) -> None:
    day = _kst(2026, 11, 23, 10, 0)
    make_call(db, call_datetime=day, status="FAILED")
    make_call(db, call_datetime=day, status="STORED")
    make_call(db, call_datetime=day, deleted_at=day)
    make_call(db, call_datetime=None, metadata_incomplete=True)

    counts = StatsRepository(db).count_by_period(StatsPeriod(), "day")

    assert counts == {date(2026, 11, 23): 2}


def test_trend_period_filter_is_kst_day_with_to_inclusive(db: Session) -> None:
    make_call(db, call_datetime=_kst(2026, 11, 22, 23, 59, 59))
    make_call(db, call_datetime=_kst(2026, 11, 24, 23, 59, 59))
    make_call(db, call_datetime=_kst(2026, 11, 25, 0, 0))
    period = StatsPeriod(from_=date(2026, 11, 23), to=date(2026, 11, 24))

    counts = StatsRepository(db).count_by_period(period, "day")

    assert counts == {date(2026, 11, 24): 1}


def test_breakdown_merges_null_and_blank_names(db: Session) -> None:
    make_call(db, agent_name="김상담")
    make_call(db, agent_name="김상담")
    make_call(db, agent_name="김상담 ")  # 저장 값 그대로 (공백 포함은 별도 행)
    make_call(db, agent_name=None)
    make_call(db, agent_name="")
    make_call(db, agent_name="   ")
    make_call(db, agent_name="이상담", deleted_at=_kst(2026, 11, 23))

    rows = StatsRepository(db).count_by_dimension(StatsPeriod(), "agent")

    assert {row.name: row.count for row in rows} == {"김상담": 2, "김상담 ": 1, None: 3}


def test_breakdown_counts_categories_by_code(db: Session) -> None:
    complaint = make_call(db, client_company="가나상사")
    make_analysis(db, complaint, category="불만")
    education = make_call(db, client_company="가나상사")
    make_analysis(db, education, category="교육 내용")
    make_call(db, client_company="가나상사")  # 분석 전

    (row,) = StatsRepository(db).count_by_dimension(StatsPeriod(), "client")

    assert row.name == "가나상사"
    assert row.count == 3
    assert row.by_category == {
        Category.INQUIRY: 0,
        Category.COMPLAINT: 1,
        Category.SUGGESTION: 0,
        Category.EDUCATION: 1,
        Category.ETC: 0,
    }


def test_breakdown_includes_missing_datetime_only_without_period(db: Session) -> None:
    make_call(db, agent_name="김상담", call_datetime=_kst(2026, 11, 23, 9, 0))
    make_call(db, agent_name="김상담", call_datetime=None)
    repo = StatsRepository(db)

    (all_time,) = repo.count_by_dimension(StatsPeriod(), "agent")
    (in_period,) = repo.count_by_dimension(StatsPeriod(from_=date(2026, 11, 23)), "agent")

    assert all_time.count == 2
    assert in_period.count == 1


def test_summary_period_applies_only_to_total_and_category(db: Session) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(hours=2)
    in_period = _kst(2026, 11, 23, 9, 0)
    out_period = _kst(2026, 10, 1, 9, 0)
    a = make_call(db, status="STORED", call_datetime=in_period)
    make_analysis(db, a, category="불만", action_status="OPEN")
    b = make_call(db, status="NEEDS_REVIEW", call_datetime=out_period)
    make_analysis(db, b, category="질의", action_status="DONE")
    make_call(db, status="FAILED", metadata_incomplete=True)
    make_call(db, status="QUEUED", status_changed_at=old, call_datetime=out_period)
    make_call(db, status="NEEDS_REVIEW", status_changed_at=old, deleted_at=old)

    repo = StatsRepository(db)
    period = StatsPeriod(from_=date(2026, 11, 23), to=date(2026, 11, 23))
    summary = repo.summary(period, stale_threshold_min=30, now=now)
    whole = repo.summary(StatsPeriod(), stale_threshold_min=30, now=now)

    assert summary.total == 1
    assert summary.by_category.model_dump() == {
        "INQUIRY": 0, "COMPLAINT": 1, "SUGGESTION": 0, "EDUCATION": 0, "ETC": 0,
    }  # fmt: skip
    queues = (
        summary.action_open,
        summary.needs_review,
        summary.metadata_incomplete,
        summary.failed,
        summary.stale,
    )
    assert queues == (1, 1, 1, 1, 1)
    assert whole.total == 4
    assert whole.by_category.INQUIRY == 1


def test_summary_empty(db: Session) -> None:
    summary = StatsRepository(db).summary(StatsPeriod(), stale_threshold_min=30)

    assert summary == StatsSummary.empty()
