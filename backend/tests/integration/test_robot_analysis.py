"""R-07 `PUT /api/robot/calls/{id}/analysis` (분석 적재, 실제 PostgreSQL).

RPA 파트의 계약 샘플(`uipath/samples/test_cases/`)을 그대로 쓴다.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Analysis, CallRecord, ProcessingLog
from app.schemas.call import CallStatus
from tests.conftest import ROBOT_IP
from tests.factories import make_analysis, make_call_record

pytestmark = pytest.mark.integration

S = CallStatus
SAMPLES = Path(__file__).resolve().parents[3] / "uipath" / "samples" / "test_cases"


def sample(name: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))
    data.update(overrides)
    return data


def put(client: TestClient, call_id: int | str, payload: dict[str, Any]) -> Any:
    return client.put(f"/api/robot/calls/{call_id}/analysis", json=payload)


def analyses(db: Session, call_id: int) -> list[Analysis]:
    return list(db.scalars(select(Analysis).where(Analysis.call_id == call_id)))


def log_count(db: Session, call_id: int) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(ProcessingLog).where(ProcessingLog.call_id == call_id)
        )
        or 0
    )


def test_success_result_is_stored_and_call_becomes_stored(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, status=S.STT_DONE)

    response = put(robot_client, call.id, sample("case01_success"))

    assert response.status_code == 200
    assert response.json() == {"call_id": call.id, "status": "STORED"}
    db.refresh(call)
    assert call.status == S.STORED
    (analysis,) = analyses(db, call.id)
    assert analysis.category == "불만"  # COMPLAINT
    assert analysis.confidence == Decimal("0.920")
    assert analysis.question_summary == sample("case01_success")["customer_question"]
    assert analysis.action_summary == sample("case01_success")["agent_action"]
    assert analysis.follow_up_required is True
    assert analysis.entities == [
        {"type": "REF_NO", "value": "주문번호 [REF]"},
        {"type": "DATE", "value": "일주일 전"},
    ]
    assert analysis.prompt_version == "v1.2"
    assert analysis.needs_review is False
    assert analysis.action_status == "OPEN"
    log = db.scalars(select(ProcessingLog).where(ProcessingLog.call_id == call.id)).one()
    assert (log.step, log.status) == ("STORE", "SUCCESS")


def test_needs_review_result_follows_the_pipelines_judgment(
    robot_client: TestClient, db: Session
) -> None:
    # 임계값으로 다시 판정하지 않는다: 신뢰도 0.55라도 판정은 결과의 status를 따른다.
    call = make_call_record(db, status=S.STT_DONE)

    response = put(robot_client, call.id, sample("case02_needs_review"))

    assert response.status_code == 200
    assert response.json()["status"] == "NEEDS_REVIEW"
    (analysis,) = analyses(db, call.id)
    assert analysis.needs_review is True
    assert analysis.category == "기타 문의"  # OTHER


def test_high_confidence_does_not_override_needs_review_status(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, status=S.STT_DONE)

    response = put(
        robot_client, call.id, sample("case01_success", status="NEEDS_REVIEW", type_confidence=0.99)
    )

    assert response.json()["status"] == "NEEDS_REVIEW"


@pytest.mark.parametrize(
    ("analysis_type", "stored"),
    [
        ("INQUIRY", "질의"),
        ("COMPLAINT", "불만"),
        ("SUGGESTION", "건의"),
        ("TRAINING", "교육 내용"),
        ("OTHER", "기타 문의"),
    ],
)
def test_five_types_are_mapped_to_stored_categories(
    robot_client: TestClient, db: Session, analysis_type: str, stored: str
) -> None:
    call = make_call_record(db, status=S.STT_DONE)

    response = put(robot_client, call.id, sample("case01_success", type=analysis_type))

    assert response.status_code == 200
    assert analyses(db, call.id)[0].category == stored


def test_original_json_is_kept_in_raw_json_without_duplicating_transcript(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, status=S.STT_DONE)
    original = sample("case01_success")

    put(robot_client, call.id, original)

    raw = analyses(db, call.id)[0].raw_json
    assert "transcript" not in raw  # 전사는 transcript 테이블(R-06)에 있다
    # 전용 컬럼이 없는 필드도 원본 그대로 남는다.
    for key in ("summary", "sentiment", "keywords", "follow_up", "pii", "source", "call_id"):
        assert raw[key] == original[key]
    assert raw["processing"]["genai_model"] == "gpt-sample"


def test_optional_fields_can_be_missing(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.STT_DONE)
    minimal = {"schema_version": "1.0", "status": "SUCCESS", "type": "INQUIRY"}

    response = put(robot_client, call.id, minimal)

    assert response.status_code == 200
    (analysis,) = analyses(db, call.id)
    assert analysis.confidence is None
    assert analysis.question_summary is None
    assert analysis.entities == []
    assert analysis.prompt_version is None
    db.refresh(call)
    assert call.duration_sec is None


# ------------------------------------------------------------------ 통화 길이


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(142.6, 143), (88.3, 88), (2.5, 3), (0.4, 0), (60, 60)],
)
def test_duration_is_stored_as_whole_seconds_rounding_half_up(
    robot_client: TestClient, db: Session, seconds: float, expected: int
) -> None:
    call = make_call_record(db, status=S.STT_DONE)
    payload = sample("case01_success")
    payload["source"]["duration_sec"] = seconds

    response = put(robot_client, call.id, payload)

    assert response.status_code == 200
    db.refresh(call)
    assert call.duration_sec == expected
    assert robot_client.get(f"/api/calls/{call.id}").json()["duration_sec"] == expected


def test_missing_duration_keeps_the_existing_value(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.STT_DONE, duration_sec=90)
    payload = sample("case01_success")
    payload["source"]["duration_sec"] = None

    response = put(robot_client, call.id, payload)

    assert response.status_code == 200
    db.refresh(call)
    assert call.duration_sec == 90


# ------------------------------------------------------------------ 멱등·재분석


def test_resend_is_idempotent(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.STT_DONE)

    first = put(robot_client, call.id, sample("case01_success"))
    again = put(robot_client, call.id, sample("case01_success"))

    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert len(analyses(db, call.id)) == 1
    assert log_count(db, call.id) == 1  # 전이 로그는 처음 한 번만


def test_reanalysis_overwrites_result_but_keeps_action_status(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, status=S.STT_DONE)
    put(robot_client, call.id, sample("case01_success"))
    (analysis,) = analyses(db, call.id)
    analysis.action_status = "DONE"  # 사람이 조치 완료로 바꾼 값
    db.flush()

    # case04: 같은 건을 새 프롬프트로 다시 분석한 결과
    response = put(robot_client, call.id, sample("case04_duplicate_update"))

    assert response.status_code == 200
    db.refresh(analysis)
    assert analysis.prompt_version == "v1.3"
    assert analysis.follow_up_required is False
    assert analysis.action_status == "DONE"
    assert len(analyses(db, call.id)) == 1


def test_retry_flow_overwrites_previous_analysis(robot_client: TestClient, db: Session) -> None:
    # STORED → 재처리 요청 → 큐 → 전사 → 분석: 새 결과가 이전 결과를 대체한다.
    call = make_call_record(db, status=S.STT_DONE)
    make_analysis(db, call, category="질의", prompt_version="old")

    response = put(robot_client, call.id, sample("case01_success"))

    assert response.status_code == 200
    (analysis,) = analyses(db, call.id)
    assert analysis.category == "불만"
    assert analysis.prompt_version == "v1.2"


# ------------------------------------------------------------------ 상태


@pytest.mark.parametrize("source", [S.REGISTERED, S.QUEUED, S.FAILED, S.RETRY_REQUESTED])
def test_other_states_are_409_and_store_nothing(
    robot_client: TestClient, db: Session, source: S
) -> None:
    call = make_call_record(db, status=source)

    response = put(robot_client, call.id, sample("case01_success"))

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == source
    assert analyses(db, call.id) == []
    db.refresh(call)
    assert call.status == source


@pytest.mark.parametrize(
    ("current", "payload_name"),
    [
        (S.STORED, "case02_needs_review"),  # 저장 완료 건에 검토 필요 결과가 뒤늦게 도착
        (S.NEEDS_REVIEW, "case01_success"),  # 검토 완료(STORED)는 웹이 한다. 로봇이 못 바꾼다
    ],
)
def test_result_with_different_outcome_than_current_state_is_409(
    robot_client: TestClient, db: Session, current: S, payload_name: str
) -> None:
    call = make_call_record(db, status=current)
    make_analysis(db, call, category="질의")

    response = put(robot_client, call.id, sample(payload_name))

    assert response.status_code == 409
    assert analyses(db, call.id)[0].category == "질의"  # 기존 결과가 유지된다
    db.refresh(call)
    assert call.status == current


def test_unknown_and_soft_deleted_calls_are_404(robot_client: TestClient, db: Session) -> None:
    from datetime import UTC, datetime

    deleted = make_call_record(db, status=S.STT_DONE, deleted_at=datetime.now(UTC))

    assert put(robot_client, 999_999, sample("case01_success")).status_code == 404
    assert put(robot_client, deleted.id, sample("case01_success")).status_code == 404


# ------------------------------------------------------------------ 입력 검증


def test_failed_result_is_rejected_because_failures_go_through_the_log_api(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, status=S.STT_DONE)

    response = put(robot_client, call.id, sample("case03_failed"))

    assert response.status_code == 422
    assert any("status" in e["loc"] for e in response.json()["detail"]["errors"])
    db.refresh(call)
    assert call.status == S.STT_DONE


def test_result_without_type_is_rejected(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.STT_DONE)

    response = put(robot_client, call.id, sample("case06_missing_required"))

    assert response.status_code == 422
    assert any("type" in e["loc"] for e in response.json()["detail"]["errors"])
    assert analyses(db, call.id) == []


def test_unsupported_schema_version_is_rejected(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.STT_DONE)

    response = put(robot_client, call.id, sample("case07_schema_version_mismatch"))

    assert response.status_code == 422
    assert any("schema_version" in e["loc"] for e in response.json()["detail"]["errors"])
    assert analyses(db, call.id) == []


def test_sample_with_null_metadata_fields_is_accepted(
    robot_client: TestClient, db: Session
) -> None:
    # 담당자·고객사 등이 null이어도 분석 적재와는 무관하다.
    call = make_call_record(db, status=S.STT_DONE)

    response = put(robot_client, call.id, sample("case05_null_fields"))

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("overrides", "loc"),
    [
        ({"type": "UNKNOWN"}, "type"),
        ({"type": "ETC"}, "type"),  # 웹 API 코드가 아니라 GenAI 결과 코드를 받는다
        ({"type": None}, "type"),
        ({"type_confidence": 1.5}, "type_confidence"),
        ({"type_confidence": -0.1}, "type_confidence"),
        ({"type_confidence": "높음"}, "type_confidence"),
        ({"status": "SUCCEEDED"}, "status"),
        ({"status": None}, "status"),
        ({"follow_up_required": "maybe"}, "follow_up_required"),
        ({"entities": [{"type": "ORG"}]}, "value"),
        ({"entities": [{"type": "ORG", "value": ""}]}, "value"),
        ({"entities": "none"}, "entities"),
        ({"processing": {"prompt_version": "v" * 21}}, "prompt_version"),
        ({"source": {"duration_sec": -1}}, "duration_sec"),
        ({"source": {"duration_sec": "2분"}}, "duration_sec"),
    ],
)
def test_invalid_field_is_422_and_changes_nothing(
    robot_client: TestClient, db: Session, overrides: dict[str, Any], loc: str
) -> None:
    call = make_call_record(db, status=S.STT_DONE)

    response = put(robot_client, call.id, sample("case01_success", **overrides))

    assert response.status_code == 422
    assert any(loc in e["loc"] for e in response.json()["detail"]["errors"])
    assert analyses(db, call.id) == []
    db.refresh(call)
    assert call.status == S.STT_DONE


def test_validation_error_does_not_echo_customer_content(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, status=S.STT_DONE)
    secret = "고객이 말한 민감한 내용"

    response = put(robot_client, call.id, sample("case01_success", type="UNKNOWN", summary=secret))

    assert response.status_code == 422
    assert secret not in response.text


def test_missing_body_fields_are_422(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.STT_DONE)

    assert put(robot_client, call.id, {}).status_code == 422


def test_unauthenticated_request_is_401_and_stores_nothing(robot_app: FastAPI, db: Session) -> None:
    call = make_call_record(db, status=S.STT_DONE)
    client = TestClient(robot_app, client=(ROBOT_IP, 50000))

    response = put(client, call.id, sample("case01_success"))

    assert response.status_code == 401
    assert analyses(db, call.id) == []


# ------------------------------------------------------------------ 웹 조회와의 연결


def test_stored_result_is_visible_in_web_detail(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.QUEUED)
    sample_json = sample("case01_success")
    robot_client.put(
        f"/api/robot/calls/{call.id}/transcript",
        json={
            "segments": sample_json["transcript"]["segments"],
            "full_text": sample_json["transcript"]["full_text"],
            "stt_engine": sample_json["processing"]["stt_engine"],
        },
    )
    put(robot_client, call.id, sample_json)

    detail = robot_client.get(f"/api/calls/{call.id}").json()

    assert detail["status"] == "STORED"
    assert detail["analysis"]["category"] == "COMPLAINT"
    assert detail["analysis"]["follow_up_required"] is True
    assert detail["transcript"]["segments"][0]["speaker"] == "AGENT"
    assert [log["step"] for log in detail["processing_log"]] == ["STT", "STORE"]
    assert isinstance(db.get(CallRecord, call.id), CallRecord)
