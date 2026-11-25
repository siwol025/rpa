"""엑셀 보고서 유스케이스: 기간 안의 상담을 RPA 파트 보고서 양식에 채운다."""

import re
from functools import lru_cache
from pathlib import Path

from app.models import Analysis, CallRecord, ProcessingLog
from app.repositories.report_repository import ReportRepository
from app.schemas.call import CallStatus
from app.schemas.report import ReportPeriod
from app.services.excel_report import CellValue, TableData, fill_template

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "templates" / "report.xlsx"

# 로봇 보고서(uipath/Flow_JsonToExcel.xaml)와 같은 표기. 대시보드 수식이 이 값을 센다.
STATUS_LABELS = {CallStatus.STORED: "정상", CallStatus.NEEDS_REVIEW: "확인필요"}
FOLLOW_UP_LABELS = {True: "필요", False: "불필요"}

# 실패 로그 메시지: "[robot] QUEUED -> FAILED: [STT] 사유" 또는 "[robot] [STT] 사유".
_FAILURE_MESSAGE = re.compile(
    r"^\[[^\]]*\] (?:\S+ -> \S+(?:: |$))?(?:\[(?P<stage>[A-Z]+)\] ?)?(?P<reason>.*)$", re.S
)


@lru_cache(maxsize=1)
def load_template() -> bytes:
    return TEMPLATE_PATH.read_bytes()


def report_file_name(period: ReportPeriod) -> str:
    return f"콜센터_보고서_{period.start:%Y%m%d}-{period.end:%Y%m%d}.xlsx"


def parse_failure(message: str | None, step: str) -> tuple[str | None, str | None]:
    """실패 로그에서 (오류 단계, 사유)를 꺼낸다. 단계 표기가 없으면 로그의 처리 단계."""
    if message is None:
        return step, None
    match = _FAILURE_MESSAGE.match(message)
    if match is None:
        return step, message
    return match["stage"] or step, match["reason"] or None


def _text(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    return value if isinstance(value, str) else None


def _call_row(call: CallRecord, analysis: Analysis) -> list[CellValue]:
    raw = analysis.raw_json or {}
    follow_up = analysis.follow_up_required
    return [
        call.id,
        call.call_datetime,
        call.agent_name,
        call.client_company,
        analysis.category,
        analysis.question_summary,
        analysis.action_summary,
        _text(raw, "summary"),
        None if follow_up is None else FOLLOW_UP_LABELS[follow_up],
        _text(raw, "follow_up"),
        STATUS_LABELS[CallStatus(call.status)],
    ]


def _error_row(call: CallRecord, log: ProcessingLog | None) -> list[CellValue]:
    stage, reason = parse_failure(log.message, log.step) if log else (None, None)
    return [call.id, call.original_name, stage, reason, call.created_at, call.retry_count]


class ReportService:
    def __init__(self, repository: ReportRepository, template: bytes | None = None) -> None:
        self._repository = repository
        self._template = template

    def build(self, period: ReportPeriod) -> bytes:
        calls = [_call_row(c, a) for c, a in self._repository.analyzed_calls(period)]
        errors = [_error_row(c, log) for c, log in self._repository.failed_calls(period)]
        return fill_template(
            self._template or load_template(),
            [TableData("tblCalls", calls), TableData("tblErrors", errors)],
        )
