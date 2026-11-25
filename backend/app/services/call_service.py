"""웹 상담 유스케이스: 목록·상세 조회, 메타데이터 보정·분석 수정·검토 완료, 삭제."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import CallRecord
from app.repositories.call_repository import CallRepository
from app.schemas.call import (
    CallBase,
    CallDetail,
    CallListItem,
    CallListQuery,
    CallStatus,
    CallUpdateRequest,
)
from app.schemas.common import KST, Page, PageParams
from app.services.call_metadata import is_metadata_incomplete
from app.services.state_machine import CallStateMachine, is_stale


def _base_fields(call: CallRecord, stale_threshold_min: int, now: datetime) -> dict[str, Any]:
    fields = {name: getattr(call, name) for name in CallBase.model_fields if name != "is_stale"}
    return {**fields, "is_stale": is_stale(call, stale_threshold_min, now)}


@dataclass(frozen=True)
class FieldChange:
    field: str
    before: str | None
    after: str | None


def history_value(value: object) -> str | None:
    """수정 이력 저장 문자열. 시각은 응답과 같은 초 단위 ISO 8601 `+09:00`."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(KST).replace(microsecond=0).isoformat()
    return str(value)


def apply_changes(target: object, changes: dict[str, Any]) -> list[FieldChange]:
    """값이 다른 필드만 대입하고 바뀐 필드 목록을 돌려준다. 같은 순간의 시각은 같은 값이다."""
    applied: list[FieldChange] = []
    for field, new in changes.items():
        old = getattr(target, field)
        if old == new:
            continue
        setattr(target, field, new)
        applied.append(FieldChange(field, history_value(old), history_value(new)))
    return applied


class CallService:
    def __init__(
        self, repository: CallRepository, session: Session, *, stale_threshold_min: int
    ) -> None:
        self._repository = repository
        self._session = session  # 유스케이스 단위 트랜잭션: 쓰기 메서드가 커밋한다.
        self._stale_threshold_min = stale_threshold_min

    def list_calls(self, query: CallListQuery, page: PageParams) -> Page[CallListItem]:
        now = datetime.now(UTC)  # 정체 필터와 is_stale을 같은 시각으로 판단
        threshold = self._stale_threshold_min
        rows = self._repository.list_calls(
            query, offset=page.offset, limit=page.size, stale_threshold_min=threshold, now=now
        )
        items = [
            CallListItem.model_validate(
                {
                    **_base_fields(call, threshold, now),
                    "category": category,
                    "question_summary": question_summary,
                    "action_status": action_status,
                }
            )
            for call, category, question_summary, action_status in rows
        ]
        total = self._repository.count_calls(query, stale_threshold_min=threshold, now=now)
        return Page(items=items, page=page.page, size=page.size, total=total)

    def get_call(self, call_id: int) -> CallDetail:
        call = self._repository.get_call(call_id)
        if call is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return CallDetail.model_validate(
            {
                **_base_fields(call, self._stale_threshold_min, datetime.now(UTC)),
                "transcript": call.transcript,
                "analysis": call.analysis,
                "processing_log": self._repository.list_logs(call_id),
            }
        )

    def update_call(self, call_id: int, request: CallUpdateRequest) -> CallDetail:
        """보낸 키만 바꾸고 바뀐 필드마다 이력 1행. `review_completed`면 `NEEDS_REVIEW → STORED`.

        409(분석 결과 없음·검토 완료 불가)는 어떤 값도 바꾸기 전에 낸다.
        """
        call = self._lock(call_id)
        analysis_changes = request.analysis_changes()
        if analysis_changes and call.analysis is None:
            raise AppError(ErrorCode.INVALID_STATE_TRANSITION, "분석 결과가 없는 상담입니다.")
        status_change: list[FieldChange] = []
        if request.review_completed:
            before = call.status
            # 같은 트랜잭션이라 이미 잡은 행 잠금을 다시 잡아도 막히지 않는다. flush까지만 한다.
            CallStateMachine(
                self._session, stale_threshold_min=self._stale_threshold_min
            ).transition(call_id, CallStatus.STORED, actor="web", reason="검토 완료")
            if call.analysis is not None:
                call.analysis.needs_review = False
            status_change.append(FieldChange("status", before, call.status))

        metadata = request.metadata_changes()
        changes = apply_changes(call, metadata)
        if metadata:
            call.metadata_incomplete = is_metadata_incomplete(call.agent_name, call.call_datetime)
        if analysis_changes:
            changes += apply_changes(call.analysis, analysis_changes)
        for change in changes + status_change:
            self._repository.add_edit_history(
                call_id, change.field, change.before, change.after, editor=request.editor
            )
        self._session.commit()
        return self.get_call(call_id)

    def delete_call(self, call_id: int, *, editor: str | None = None) -> None:
        """소프트 삭제. 상태·하위 데이터는 그대로 두고 삭제 이력을 남긴다."""
        call = self._lock(call_id)
        call.deleted_at = datetime.now(UTC)
        self._repository.add_edit_history(
            call_id, "deleted_at", None, history_value(call.deleted_at), editor=editor
        )
        self._session.commit()

    def _lock(self, call_id: int) -> CallRecord:
        call = self._repository.lock_call(call_id)
        if call is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return call
