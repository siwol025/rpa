from datetime import UTC, datetime
from typing import Any

from app.schemas.call import CallListItem

_BASE: dict[str, Any] = {
    "id": 1,
    "source_type": "DRIVE",
    "original_name": "a.wav",
    "duration_sec": 60,
    "agent_name": None,
    "client_company": None,
    "call_datetime": None,
    "metadata_incomplete": True,
    "status": "STORED",
    "status_changed_at": datetime(2026, 11, 23, 5, 30, 5, 999_999, tzinfo=UTC),
    "retry_count": 0,
    "created_at": datetime(2026, 11, 23, 5, 0, tzinfo=UTC),
}


def test_list_item_maps_db_category_to_code() -> None:
    item = CallListItem.model_validate(
        {**_BASE, "category": "불만", "question_summary": "q", "action_status": None}
    )

    assert item.model_dump(mode="json")["category"] == "COMPLAINT"


def test_list_item_without_analysis_has_null_fields() -> None:
    item = CallListItem.model_validate(
        {**_BASE, "category": None, "question_summary": None, "action_status": None}
    )

    body = item.model_dump(mode="json")
    assert body["category"] is None
    assert body["call_datetime"] is None
    assert body["status_changed_at"] == "2026-11-23T14:30:05+09:00"
