from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

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


def test_detail_serializes_entities_as_list_of_type_value() -> None:
    # STT 결과(stt/schema/call_schema.json)의 entities는 [{type, value}] 배열이다.
    analysis = SimpleNamespace(
        category="불만",
        confidence=None,
        question_summary=None,
        action_summary=None,
        follow_up_required=None,
        action_status=None,
        entities=[
            {"type": "REF_NO", "value": "주문번호 [REF]"},
            {"type": "DATE", "value": "일주일 전"},
        ],
        needs_review=None,
    )
    detail = CallDetail.model_validate(
        {**_BASE, "transcript": None, "analysis": analysis, "processing_log": []}
    )

    assert detail.model_dump(mode="json")["analysis"]["entities"] == [
        {"type": "REF_NO", "value": "주문번호 [REF]"},
        {"type": "DATE", "value": "일주일 전"},
    ]


def test_detail_serializes_segments_in_stt_format() -> None:
    # STT 결과(stt/schema/call_schema.json)의 segments 형식 그대로 내보낸다.
    segments = [
        {"speaker": "AGENT", "start_sec": 0.4, "end_sec": 3.1, "text": "안녕하세요"},
        {"speaker": "UNKNOWN", "start_sec": 3.6, "end_sec": 6.0, "text": "네"},
    ]
    detail = CallDetail.model_validate(
        {
            **_BASE,
            "transcript": SimpleNamespace(segments=segments),
            "analysis": None,
            "processing_log": [],
        }
    )

    assert detail.model_dump(mode="json")["transcript"]["segments"] == segments


def test_detail_rejects_unknown_speaker() -> None:
    with pytest.raises(ValidationError):
        CallDetail.model_validate(
            {
                **_BASE,
                "transcript": SimpleNamespace(
                    segments=[{"speaker": "BOT", "start_sec": 0, "end_sec": 1, "text": "x"}]
                ),
                "analysis": None,
                "processing_log": [],
            }
        )
