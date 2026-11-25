"""엑셀 보고서: 실제 PostgreSQL 데이터로 받은 파일의 행을 확인한다."""

import io
from datetime import UTC, datetime

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.factories import make_analysis, make_call, make_log

pytestmark = pytest.mark.integration

PERIOD = {"from": "2026-11-01", "to": "2026-11-30"}


def _kst(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 11, day, hour - 9, tzinfo=UTC)


def _rows(api: TestClient, sheet: str) -> list[list[object]]:
    response = api.get("/api/reports/excel", params=PERIOD)
    assert response.status_code == 200
    ws = openpyxl.load_workbook(io.BytesIO(response.content))[sheet]
    width = 11 if sheet == "통화이력" else 6
    return [
        [c.value for c in row][:width]
        for row in ws.iter_rows(min_row=2)
        if row[0].value is not None
    ]


def test_call_sheet_includes_only_analyzed_calls_in_period(api: TestClient, db: Session) -> None:
    late = make_call(db, status="NEEDS_REVIEW", call_datetime=_kst(20), agent_name="김상담")
    make_analysis(db, late, category="불만", follow_up_required=True, raw_json={"summary": "요약"})
    early = make_call(db, status="STORED", call_datetime=_kst(2))
    make_analysis(db, early, category="질의", follow_up_required=False)
    last_minute = make_call(  # 11-30 23:59 KST: 포함
        db, status="STORED", call_datetime=datetime(2026, 11, 30, 14, 59, tzinfo=UTC)
    )
    make_analysis(db, last_minute)
    no_datetime = make_call(db, status="STORED", call_datetime=None, created_at=_kst(15))
    make_analysis(db, no_datetime)
    # 제외: 기간 밖(10-31 23:59 KST), 일시 없음 + 기간 밖 등록, 처리 중, 분석 없음, 삭제
    outside = make_call(
        db, status="STORED", call_datetime=datetime(2026, 10, 31, 14, 59, tzinfo=UTC)
    )
    make_analysis(db, outside)
    old = make_call(
        db, status="STORED", call_datetime=None, created_at=datetime(2026, 10, 15, tzinfo=UTC)
    )
    make_analysis(db, old)
    make_call(db, status="QUEUED", call_datetime=_kst(3))
    make_call(db, status="STORED", call_datetime=_kst(3))
    deleted = make_call(db, status="STORED", call_datetime=_kst(4), deleted_at=_kst(5))
    make_analysis(db, deleted)

    rows = _rows(api, "통화이력")

    assert [row[0] for row in rows] == [early.id, late.id, last_minute.id, no_datetime.id]
    assert rows[0][4] == "질의" and rows[0][8] == "불필요" and rows[0][10] == "정상"
    assert rows[1][1] == datetime(2026, 11, 20, 12, 0)
    assert rows[1][2] == "김상담" and rows[1][7] == "요약" and rows[1][8] == "필요"
    assert rows[1][10] == "확인필요"
    assert rows[3][1] is None


def test_error_sheet_uses_latest_fail_log(api: TestClient, db: Session) -> None:
    failed = make_call(
        db, status="FAILED", call_datetime=_kst(10), original_name="b.wav", retry_count=1
    )
    fail = "[robot] QUEUED -> FAILED: "
    make_log(
        db,
        failed,
        step="STT",
        status="FAIL",
        message=f"{fail}[STT] 첫 실패",
        created_at=_kst(10, 13),
    )
    make_log(
        db,
        failed,
        step="GENAI",
        status="FAIL",
        message=f"{fail}[GENAI] 응답 오류",
        created_at=_kst(10, 14),
    )
    make_log(db, failed, step="STT", status="SUCCESS", created_at=_kst(10, 15))
    no_log = make_call(db, status="FAILED", call_datetime=_kst(11))

    rows = _rows(api, "예외")

    assert rows[0][:4] == [failed.id, "b.wav", "GENAI", "응답 오류"]
    assert rows[0][5] == 1
    assert rows[1][0] == no_log.id and rows[1][2:4] == [None, None]


def test_empty_period_returns_blank_template(api: TestClient) -> None:
    assert _rows(api, "통화이력") == []
    assert _rows(api, "예외") == []
