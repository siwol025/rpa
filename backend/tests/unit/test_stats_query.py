from sqlalchemy import create_engine, func, select

from app.models import CallRecord
from app.repositories.stats_repository import dimension_column, period_column
from app.schemas.stats import Granularity

_PG = create_engine("postgresql+psycopg://").dialect  # 연결하지 않고 SQL 문자열만 만든다


def test_period_column_truncates_in_asia_seoul() -> None:
    sql = str(period_column("week").compile(dialect=_PG))

    assert sql == "date_trunc('week', timezone('Asia/Seoul', call_record.call_datetime))"
    assert "+09:00" not in sql


def test_period_column_has_no_bind_params() -> None:
    # 단위·시간대가 상수라 SELECT·GROUP BY 표현식이 항상 같게 렌더링된다.
    granularities: list[Granularity] = ["day", "week", "month"]
    for granularity in granularities:
        compiled = period_column(granularity).compile(dialect=_PG)
        assert compiled.params == {}


def test_dimension_column_merges_blank_into_null_and_reuses_one_bind() -> None:
    name = dimension_column("client")
    stmt = select(name, func.count()).select_from(CallRecord).group_by(name)
    compiled = stmt.compile(dialect=_PG)
    sql = str(compiled)

    assert "CASE WHEN (btrim(call_record.client_company) = " in sql
    assert "ELSE call_record.client_company END" in sql
    assert "GROUP BY" in sql
    # 같은 라벨 객체를 쓰면 바인드 파라미터가 하나다 (따로 만들면 GroupingError).
    assert list(compiled.params.values()) == [""]
