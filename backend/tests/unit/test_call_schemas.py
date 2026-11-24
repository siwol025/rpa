from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.schemas.call import CallDetail, CallListItem

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


def test_detail_reads_orm_like_objects_and_serializes() -> None:
    analysis = SimpleNamespace(
        category="교육 내용",
        confidence=Decimal("0.850"),
        question_summary="환불 문의",
        action_summary="환불 처리",
        follow_up_required=None,
        action_status=None,
        entities=None,
        needs_review=None,
        raw_json={"secret": "x"},
    )
    log = SimpleNamespace(
        step="REGISTER", status="SUCCESS", message=None, created_at=_BASE["created_at"]
    )
    detail = CallDetail.model_validate(
        {**_BASE, "transcript": None, "analysis": analysis, "processing_log": [log]}
    )

    body = detail.model_dump(mode="json")
    assert body["transcript"] is None
    assert body["analysis"]["category"] == "EDUCATION"
    assert body["analysis"]["confidence"] == 0.85
    assert body["analysis"]["follow_up_required"] is None
    assert body["analysis"]["action_status"] is None
    assert "raw_json" not in body["analysis"]
    assert body["processing_log"] == [
        {
            "step": "REGISTER",
            "status": "SUCCESS",
            "message": None,
            "created_at": "2026-11-23T14:00:00+09:00",
        }
    ]
    assert "object_key" not in body
    assert "file_hash" not in body
