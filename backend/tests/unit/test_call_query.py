from datetime import date, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import and_, create_engine
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.repositories.call_repository import (
    CallRepository,
    filter_conditions,
    kst_day_start,
    order_by_clause,
)
from app.schemas.call import CallListQuery, CallStatus, Category
from app.schemas.common import KST

_PG = create_engine("postgresql+psycopg://").dialect  # 연결하지 않고 SQL 문자열만 만든다


def _sql(query: CallListQuery) -> tuple[str, dict[str, object]]:
    compiled = and_(*filter_conditions(query)).compile(dialect=_PG)
    return str(compiled), compiled.params


def test_kst_day_start_is_aware_midnight() -> None:
    assert kst_day_start(date(2026, 11, 23)) == datetime(2026, 11, 23, tzinfo=KST)


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("-created_at", ["call_record.created_at DESC", "call_record.id DESC"]),
        ("created_at", ["call_record.created_at ASC", "call_record.id ASC"]),
        ("status_changed_at", ["call_record.status_changed_at ASC", "call_record.id ASC"]),
        ("-call_datetime", ["call_record.call_datetime DESC NULLS LAST", "call_record.id DESC"]),
        ("call_datetime", ["call_record.call_datetime ASC NULLS LAST", "call_record.id ASC"]),
    ],
)
def test_order_by_clause(sort: str, expected: list[str]) -> None:
    clauses = order_by_clause(sort)  # type: ignore[arg-type]

    assert [str(c.compile(dialect=_PG)) for c in clauses] == expected


def test_no_filter_still_excludes_soft_deleted() -> None:
    sql, _ = _sql(CallListQuery())

    assert sql == "call_record.deleted_at IS NULL"


def test_period_uses_kst_day_bounds_with_to_inclusive() -> None:
    sql, params = _sql(CallListQuery(from_=date(2026, 11, 1), to=date(2026, 11, 23)))

    assert "call_record.call_datetime >= " in sql
    assert "call_record.call_datetime < " in sql
    assert datetime(2026, 11, 1, tzinfo=KST) in params.values()
    assert datetime(2026, 11, 24, tzinfo=KST) in params.values()


def test_keyword_searches_three_columns_with_escaped_wildcards() -> None:
    sql, params = _sql(CallListQuery(q=" 50%_ "))

    for column in (
        "analysis.question_summary",
        "analysis.action_summary",
        "transcript.corrected_text",
    ):
        assert f"{column} ILIKE" in sql
    assert "ESCAPE '/'" in sql
    assert set(params.values()) == {"50/%/_"}


def test_blank_keyword_is_ignored() -> None:
    query = CallListQuery(q="   ")

    assert query.keyword is None
    assert _sql(query)[0] == "call_record.deleted_at IS NULL"


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_agent_and_client_are_ignored(value: str) -> None:
    query = CallListQuery(agent=value, client=value)

    assert _sql(query)[0] == "call_record.deleted_at IS NULL"


def test_multi_value_and_exact_match_filters() -> None:
    sql, params = _sql(
        CallListQuery(
            status=[CallStatus.FAILED, CallStatus.NEEDS_REVIEW],
            category=[Category.COMPLAINT],
            agent="김상담",
            client="가나상사",
            metadata_incomplete=False,
        )
    )

    assert "call_record.status IN" in sql
    assert "analysis.category IN" in sql
    assert "call_record.agent_name = " in sql
    assert "call_record.client_company = " in sql
    assert "call_record.metadata_incomplete IS false" in sql
    assert params["agent_name_1"] == "김상담"
    assert params["category_1"] == ["불만"]  # API 코드 → DB 저장 값


def test_from_after_to_raises_validation_error() -> None:
    with pytest.raises(AppError) as exc_info:
        CallListQuery(from_=date(2026, 11, 2), to=date(2026, 11, 1))

    assert exc_info.value.code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.detail == {
        "errors": [
            {
                "loc": ["query", "from"],
                "msg": "from은 to보다 늦을 수 없습니다",
                "type": "date_range",
            }
        ]
    }


def test_same_day_range_is_allowed() -> None:
    CallListQuery(from_=date(2026, 11, 1), to=date(2026, 11, 1))


class _CaptureSession:
    """실행하지 않고 넘겨받은 문장만 모은다."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    def scalars(self, stmt: Any) -> Any:
        self.statements.append(stmt)
        return SimpleNamespace(one_or_none=lambda: None)


def test_lock_call_selects_only_call_record_for_update() -> None:
    # PostgreSQL은 OUTER JOIN의 NULL 가능 쪽에 FOR UPDATE를 허용하지 않는다 → JOIN이 없어야 한다.
    capture = _CaptureSession()

    assert CallRepository(cast(Session, capture)).lock_call(7) is None

    (stmt,) = capture.statements
    compiled = stmt.compile(dialect=_PG)
    sql = str(compiled)
    assert sql.endswith("FOR UPDATE")
    assert "JOIN" not in sql
    assert "FROM call_record \nWHERE call_record.id = " in sql
    assert "call_record.deleted_at IS NULL" in sql
    assert 7 in compiled.params.values()
