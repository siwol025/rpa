"""엑셀 보고서 조회 쿼리."""

from datetime import timedelta

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import Session

from app.models import Analysis, CallRecord, ProcessingLog
from app.repositories.call_repository import kst_day_start
from app.schemas.call import CallStatus
from app.schemas.report import ReportPeriod

REPORT_STATUSES = (CallStatus.STORED, CallStatus.NEEDS_REVIEW)


def in_report_period(period: ReportPeriod) -> ColumnElement[bool]:
    """통화 일시가 기간 안이거나, 통화 일시가 없고 등록 시각이 기간 안(KST 날짜)."""
    start = kst_day_start(period.start)
    end = kst_day_start(period.end + timedelta(days=1))
    return or_(
        and_(CallRecord.call_datetime >= start, CallRecord.call_datetime < end),
        and_(
            CallRecord.call_datetime.is_(None),
            CallRecord.created_at >= start,
            CallRecord.created_at < end,
        ),
    )


_ORDER = (CallRecord.call_datetime.asc().nulls_last(), CallRecord.id.asc())


class ReportRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def analyzed_calls(self, period: ReportPeriod) -> list[tuple[CallRecord, Analysis]]:
        """분석이 끝난(`STORED`·`NEEDS_REVIEW`) 삭제되지 않은 건과 분석 결과."""
        stmt = (
            select(CallRecord, Analysis)
            .join(Analysis, Analysis.call_id == CallRecord.id)
            .where(
                CallRecord.deleted_at.is_(None),
                CallRecord.status.in_(REPORT_STATUSES),
                in_report_period(period),
            )
            .order_by(*_ORDER)
        )
        return [(call, analysis) for call, analysis in self._session.execute(stmt)]

    def failed_calls(self, period: ReportPeriod) -> list[tuple[CallRecord, ProcessingLog | None]]:
        """`FAILED` 건과 마지막 `FAIL` 처리 로그(없으면 None)."""
        calls = list(
            self._session.scalars(
                select(CallRecord)
                .where(
                    CallRecord.deleted_at.is_(None),
                    CallRecord.status == CallStatus.FAILED,
                    in_report_period(period),
                )
                .order_by(*_ORDER)
            )
        )
        if not calls:
            return []
        logs = self._session.scalars(
            select(ProcessingLog)
            .where(ProcessingLog.call_id.in_([c.id for c in calls]), ProcessingLog.status == "FAIL")
            .order_by(
                ProcessingLog.call_id, ProcessingLog.created_at.desc(), ProcessingLog.id.desc()
            )
            .distinct(ProcessingLog.call_id)
        )
        by_call = {log.call_id: log for log in logs}
        return [(call, by_call.get(call.id)) for call in calls]
