"""R-06 `PUT /api/robot/calls/{id}/transcript` (전사 적재, 실제 PostgreSQL)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ProcessingLog, Transcript
from app.schemas.call import CallStatus
from tests.conftest import ROBOT_IP
from tests.factories import make_call_record, make_transcript

pytestmark = pytest.mark.integration

S = CallStatus

SEGMENTS = [
    {"speaker": "AGENT", "start_sec": 0.4, "end_sec": 3.1, "text": "안녕하세요, 고객센터입니다."},
    {"speaker": "CUSTOMER", "start_sec": 3.6, "end_sec": 6.0, "text": "주문한 물건이 안 왔어요."},
    {"speaker": "UNKNOWN", "start_sec": 6.0, "end_sec": 6.0, "text": ""},
]
FULL_TEXT = "[상담원] 안녕하세요, 고객센터입니다.\n[고객] 주문한 물건이 안 왔어요."


def body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "segments": SEGMENTS,
        "full_text": FULL_TEXT,
        "stt_engine": "clova-speech",
    }
    payload.update(overrides)
    return payload


def put(client: TestClient, call_id: int | str, payload: dict[str, Any]) -> Any:
    return client.put(f"/api/robot/calls/{call_id}/transcript", json=payload)


def transcripts(db: Session, call_id: int) -> list[Transcript]:
    return list(db.scalars(select(Transcript).where(Transcript.call_id == call_id)))


def log_count(db: Session, call_id: int) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(ProcessingLog).where(ProcessingLog.call_id == call_id)
        )
        or 0
    )


def test_put_transcript_stores_segments_and_moves_to_stt_done(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, status=S.QUEUED)

    response = put(robot_client, call.id, body())

    assert response.status_code == 200
    assert response.json() == {"call_id": call.id, "status": "STT_DONE"}
    db.refresh(call)
    assert call.status == S.STT_DONE
    (transcript,) = transcripts(db, call.id)
    assert transcript.segments == SEGMENTS
    assert transcript.corrected_text == FULL_TEXT
    assert transcript.stt_engine == "clova-speech"
    log = db.scalars(select(ProcessingLog).where(ProcessingLog.call_id == call.id)).one()
    assert (log.step, log.status) == ("STT", "SUCCESS")


def test_optional_fields_can_be_omitted_or_null(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.QUEUED)

    response = put(robot_client, call.id, {"segments": SEGMENTS})

    assert response.status_code == 200
    (transcript,) = transcripts(db, call.id)
    assert transcript.corrected_text is None
    assert transcript.stt_engine is None


def test_empty_segments_are_accepted(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.QUEUED)

    response = put(robot_client, call.id, body(segments=[], full_text=None))

    assert response.status_code == 200
    assert transcripts(db, call.id)[0].segments == []


def test_resend_is_idempotent_and_overwrites_without_second_transition(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, status=S.QUEUED)

    first = put(robot_client, call.id, body())
    again = put(robot_client, call.id, body())
    changed = put(robot_client, call.id, body(full_text="수정된 전사", stt_engine="other"))

    assert first.status_code == again.status_code == changed.status_code == 200
    assert first.json() == again.json() == changed.json()
    (transcript,) = transcripts(db, call.id)  # 행이 늘지 않는다
    assert transcript.corrected_text == "수정된 전사"
    assert transcript.stt_engine == "other"
    assert log_count(db, call.id) == 1  # 전이 로그는 처음 한 번만


def test_stt_done_call_with_existing_transcript_is_overwritten(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, status=S.STT_DONE)
    make_transcript(db, call, corrected_text="이전 전사")

    response = put(robot_client, call.id, body())

    assert response.status_code == 200
    (transcript,) = transcripts(db, call.id)
    assert transcript.corrected_text == FULL_TEXT


@pytest.mark.parametrize(
    "source", [S.REGISTERED, S.STORED, S.NEEDS_REVIEW, S.FAILED, S.RETRY_REQUESTED]
)
def test_other_states_are_409_and_store_nothing(
    robot_client: TestClient, db: Session, source: S
) -> None:
    call = make_call_record(db, status=source)

    response = put(robot_client, call.id, body())

    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_STATE_TRANSITION"
    assert response.json()["detail"]["current_status"] == source
    assert transcripts(db, call.id) == []
    db.refresh(call)
    assert call.status == source


def test_unknown_and_soft_deleted_calls_are_404(robot_client: TestClient, db: Session) -> None:
    deleted = make_call_record(db, status=S.QUEUED, deleted_at=datetime.now(UTC))

    assert put(robot_client, 999_999, body()).status_code == 404
    assert put(robot_client, deleted.id, body()).status_code == 404


@pytest.mark.parametrize(
    ("payload", "loc"),
    [
        ({}, "segments"),
        ({"segments": None}, "segments"),
        ({"segments": "text"}, "segments"),
        ({"segments": [{"speaker": "AGENT", "start_sec": 0, "end_sec": 1}]}, "text"),
        ({"segments": [{"speaker": "BOT", "start_sec": 0, "end_sec": 1, "text": "x"}]}, "speaker"),
        (
            {"segments": [{"speaker": "AGENT", "start_sec": -1, "end_sec": 1, "text": "x"}]},
            "start_sec",
        ),
        (
            {"segments": [{"speaker": "AGENT", "start_sec": 0, "end_sec": -1, "text": "x"}]},
            "end_sec",
        ),
        (
            {"segments": [{"speaker": "AGENT", "start_sec": 5, "end_sec": 4, "text": "x"}]},
            "segments",
        ),
        (
            {"segments": [{"speaker": "AGENT", "start_sec": "a", "end_sec": 1, "text": "x"}]},
            "start_sec",
        ),
        ({"segments": [], "stt_engine": "가" * 51}, "stt_engine"),
    ],
)
def test_invalid_body_is_422_and_changes_nothing(
    robot_client: TestClient, db: Session, payload: dict[str, Any], loc: str
) -> None:
    call = make_call_record(db, status=S.QUEUED)

    response = put(robot_client, call.id, payload)

    assert response.status_code == 422
    assert any(loc in error["loc"] for error in response.json()["detail"]["errors"])
    assert transcripts(db, call.id) == []
    db.refresh(call)
    assert call.status == S.QUEUED


def test_segment_text_is_not_echoed_in_validation_errors(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, status=S.QUEUED)
    secret = "고객의 민감한 발화 내용"

    response = put(
        robot_client,
        call.id,
        {"segments": [{"speaker": "BOT", "start_sec": 0, "end_sec": 1, "text": secret}]},
    )

    assert response.status_code == 422
    assert secret not in response.text


def test_unauthenticated_request_is_401_and_stores_nothing(robot_app: FastAPI, db: Session) -> None:
    call = make_call_record(db, status=S.QUEUED)
    client = TestClient(robot_app, client=(ROBOT_IP, 50000))

    response = put(client, call.id, body())

    assert response.status_code == 401
    assert transcripts(db, call.id) == []
