"""웹 상담 조회 유스케이스 (W-01 목록)."""

from typing import Any

from app.models import CallRecord
from app.repositories.call_repository import CallRepository
from app.schemas.call import CallBase, CallListItem, CallListQuery
from app.schemas.common import Page, PageParams


def _base_fields(call: CallRecord) -> dict[str, Any]:
    return {name: getattr(call, name) for name in CallBase.model_fields}


class CallService:
    def __init__(self, repository: CallRepository) -> None:
        self._repository = repository

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
