"""웹 상담 유스케이스: 목록·상세 조회, 삭제."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import CallRecord
from app.repositories.call_repository import CallRepository
from app.schemas.call import CallBase, CallDetail, CallListItem, CallListQuery
from app.schemas.common import KST, Page, PageParams


def _base_fields(call: CallRecord) -> dict[str, Any]:
    return {name: getattr(call, name) for name in CallBase.model_fields}


def history_value(value: object) -> str | None:
    """수정 이력 저장 문자열. 시각은 응답과 같은 초 단위 ISO 8601 `+09:00`."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(KST).replace(microsecond=0).isoformat()
    return str(value)


class CallService:
    def __init__(self, repository: CallRepository, session: Session) -> None:
        self._repository = repository
        self._session = session  # 유스케이스 단위 트랜잭션: 쓰기 메서드가 커밋한다.

    def list_calls(self, query: CallListQuery, page: PageParams) -> Page[CallListItem]:
        rows = self._repository.list_calls(query, offset=page.offset, limit=page.size)
        items = [
            CallListItem.model_validate(
                {
                    **_base_fields(call),
                    "category": category,
                    "question_summary": question_summary,
                    "action_status": action_status,
                }
            )
            for call, category, question_summary, action_status in rows
        ]
        total = self._repository.count_calls(query)
        return Page(items=items, page=page.page, size=page.size, total=total)

    def get_call(self, call_id: int) -> CallDetail:
        call = self._repository.get_call(call_id)
        if call is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return CallDetail.model_validate(
            {
                **_base_fields(call),
                "transcript": call.transcript,
                "analysis": call.analysis,
                "processing_log": self._repository.list_logs(call_id),
            }
        )

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
