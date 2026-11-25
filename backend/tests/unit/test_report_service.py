"""엑셀 보고서 유스케이스 단위 테스트: 가짜 리포지토리로 DB 없이 매핑·기간 검증을 확인한다."""

import io
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

import openpyxl
import pytest

from app.core.errors import AppError
from app.models import Analysis, CallRecord, ProcessingLog
from app.repositories.report_repository import ReportRepository
from app.schemas.common import KST
from app.schemas.report import ReportPeriod
from app.services.report_service import ReportService, parse_failure, report_file_name

T0 = datetime(2026, 11, 23, 5, 30, tzinfo=UTC)  # 14:30 KST


def _call(**overrides: Any) -> CallRecord:
    values: dict[str, Any] = {
        "id": 1,
        "source_type": "DRIVE",
        "original_name": "a.wav",
        "agent_name": "김상담",
        "client_company": "가나상사",
        "call_datetime": T0,
        "status": "STORED",
        "retry_count": 0,
        "created_at": T0,
        **overrides,
    }
    return CallRecord(**values)


def _analysis(**overrides: Any) -> Analysis:
    values: dict[str, Any] = {
        "category": "불만",
        "confidence": Decimal("0.9"),
        "question_summary": "환불 문의",
        "action_summary": "환불 안내",
        "follow_up_required": True,
        "raw_json": {"summary": "요약", "follow_up": "재연락"},
        **overrides,
    }
    return Analysis(**values)


class FakeReportRepository:
    def __init__(
        self,
        analyzed: list[tuple[CallRecord, Analysis]] | None = None,
        failed: list[tuple[CallRecord, ProcessingLog | None]] | None = None,
    ) -> None:
        self.analyzed = analyzed or []
        self.failed = failed or []
        self.periods: list[ReportPeriod] = []

    def analyzed_calls(self, period: ReportPeriod) -> list[tuple[CallRecord, Analysis]]:
        self.periods.append(period)
        return self.analyzed

    def failed_calls(self, period: ReportPeriod) -> list[tuple[CallRecord, ProcessingLog | None]]:
        return self.failed


PERIOD = ReportPeriod(from_=date(2026, 11, 1), to=date(2026, 11, 30))


def _build(repo: FakeReportRepository) -> openpyxl.Workbook:
    data = ReportService(cast(ReportRepository, repo)).build(PERIOD)
    return openpyxl.load_workbook(io.BytesIO(data))


def test_analyzed_call_maps_to_call_sheet_row() -> None:
    repo = FakeReportRepository([(_call(), _analysis())])

    row = [c.value for c in _build(repo)["통화이력"][2]][:11]

    assert row == [
        1,
        datetime(2026, 11, 23, 14, 30),
        "김상담",
        "가나상사",
        "불만",
        "환불 문의",
        "환불 안내",
        "요약",
        "필요",
        "재연락",
        "정상",
    ]
    assert repo.periods == [PERIOD]


@pytest.mark.parametrize(
    ("status", "follow_up_required", "expected"),
    [("NEEDS_REVIEW", False, ("불필요", "확인필요")), ("STORED", None, (None, "정상"))],
)
def test_status_and_follow_up_labels(
    status: str, follow_up_required: bool | None, expected: tuple[str | None, str]
) -> None:
    repo = FakeReportRepository(
        [(_call(status=status), _analysis(follow_up_required=follow_up_required))]
    )

    sheet = _build(repo)["통화이력"]

    assert (sheet["I2"].value, sheet["K2"].value) == expected


def test_missing_values_and_raw_json_fields_leave_cells_empty() -> None:
    repo = FakeReportRepository(
        [
            (
                _call(agent_name=None, client_company=None, call_datetime=None),
                _analysis(question_summary=None, raw_json={"summary": 3}),
            )
        ]
    )

    sheet = _build(repo)["통화이력"]

    assert [sheet[f"{col}2"].value for col in "BCDFHJ"] == [None] * 6


def test_failed_call_maps_to_error_sheet_row() -> None:
    log = ProcessingLog(
        step="STT", status="FAIL", message="[robot] QUEUED -> FAILED: [STT] 타임아웃"
    )
    repo = FakeReportRepository(failed=[(_call(id=7, status="FAILED", retry_count=2), log)])

    row = [c.value for c in _build(repo)["예외"][2]]

    assert row == [7, "a.wav", "STT", "타임아웃", datetime(2026, 11, 23, 14, 30), 2]


def test_failed_call_without_log_has_empty_stage_and_reason() -> None:
    repo = FakeReportRepository(failed=[(_call(id=7, status="FAILED"), None)])

    sheet = _build(repo)["예외"]

    assert (sheet["C2"].value, sheet["D2"].value) == (None, None)


@pytest.mark.parametrize(
    ("message", "step", "expected"),
    [
        ("[robot] QUEUED -> FAILED: [GENAI] 응답 형식 오류", "GENAI", ("GENAI", "응답 형식 오류")),
        ("[robot] QUEUED -> FAILED: [PII]", "STT", ("PII", None)),
        ("[robot] QUEUED -> FAILED: 디스크 부족", "STT", ("STT", "디스크 부족")),
        ("[robot] [STT] 재전송", "STT", ("STT", "재전송")),
        (None, "REGISTER", ("REGISTER", None)),
    ],
)
def test_parse_failure(
    message: str | None, step: str, expected: tuple[str | None, str | None]
) -> None:
    assert parse_failure(message, step) == expected


def test_report_file_name_uses_period() -> None:
    assert report_file_name(PERIOD) == "콜센터_보고서_20261101-20261130.xlsx"


def test_period_from_after_to_is_rejected() -> None:
    with pytest.raises(AppError) as exc_info:
        ReportPeriod(from_=date(2026, 11, 2), to=date(2026, 11, 1))

    assert exc_info.value.detail == {
        "errors": [
            {
                "loc": ["query", "from"],
                "msg": "from은 to보다 늦을 수 없습니다",
                "type": "date_range",
            }
        ]
    }


def test_period_defaults_fill_missing_dates() -> None:
    period = ReportPeriod(from_=date(2026, 1, 1))

    assert period.from_ == date(2026, 1, 1)
    assert period.to == datetime.now(KST).date()
    assert ReportPeriod(to=date(2026, 3, 1)).from_ == date(2025, 3, 1)


def test_period_longer_than_366_days_is_rejected() -> None:
    ReportPeriod(from_=date(2024, 1, 1), to=date(2024, 12, 31))  # 윤년 366일

    with pytest.raises(AppError) as exc_info:
        ReportPeriod(from_=date(2025, 1, 1), to=date(2026, 1, 2))

    (error,) = exc_info.value.detail["errors"]  # type: ignore[index]
    assert error["type"] == "period_too_long"
    assert error["loc"] == ["query", "to"]
