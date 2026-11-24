"""R-08 `POST /api/robot/calls/{id}/logs` (단계 로그·실패 보고, 실제 PostgreSQL)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProcessingLog
from app.schemas.call import CallStatus
from tests.conftest import ROBOT_IP
from tests.factories import make_call_record, make_processing_log

pytestmark = pytest.mark.integration

S = CallStatus


def post(client: TestClient, call_id: int | str, **fields: Any) -> Any:
    payload: dict[str, Any] = {"step": "STT", "status": "SUCCESS"}
    payload.update(fields)
    return client.post(f"/api/robot/calls/{call_id}/logs", json=payload)


def logs(db: Session, call_id: int) -> list[ProcessingLog]:
    return list(
        db.scalars(
            select(ProcessingLog).where(ProcessingLog.call_id == call_id).order_by(ProcessingLog.id)
        )
    )


# ------------------------------------------------------------------ 일반 단계 로그


@pytest.mark.parametrize("status", [S.REGISTERED, S.QUEUED, S.STORED, S.FAILED, S.RETRY_REQUESTED])
def test_success_log_is_recorded_without_changing_status(
    robot_client: TestClient, db: Session, status: S
) -> None:
    call = make_call_record(db, status=status)

    response = post(robot_client, call.id, step="EXCEL", status="SUCCESS", message="행 12에 기입")

    assert response.status_code == 201
    assert response.json() == {"call_id": call.id, "status": status}
    (log,) = logs(db, call.id)
    assert (log.step, log.status) == ("EXCEL", "SUCCESS")
    assert log.message == "[robot] 행 12에 기입"
    db.refresh(call)
    assert call.status == status


def test_retry_log_does_not_change_status(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.QUEUED)

    response = post(robot_client, call.id, step="GENAI", status="RETRY", message="2회차 재시도")

    assert response.status_code == 201
    assert logs(db, call.id)[0].status == "RETRY"
    db.refresh(call)
    assert call.status == S.QUEUED


def test_orchestrator_job_id_is_stored(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db)

    post(robot_client, call.id, step="QUEUE", orchestrator_job_id="job-0001")

    assert logs(db, call.id)[0].orchestrator_job_id == "job-0001"


def test_logs_accumulate_in_order(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db)
    make_processing_log(db, call, step="REGISTER")

    post(robot_client, call.id, step="QUEUE")
    post(robot_client, call.id, step="STT")

    assert [log.step for log in logs(db, call.id)] == ["REGISTER", "QUEUE", "STT"]


def test_blank_message_and_job_id_are_stored_as_null(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db)

    response = post(robot_client, call.id, message="   ", orchestrator_job_id="")

    assert response.status_code == 201
    log = logs(db, call.id)[0]
    assert log.message == "[robot]"
    assert log.orchestrator_job_id is None


# ------------------------------------------------------------------ 실패 보고


@pytest.mark.parametrize("source", [S.REGISTERED, S.QUEUED, S.STT_DONE])
def test_fail_report_moves_processing_call_to_failed(
    robot_client: TestClient, db: Session, source: S
) -> None:
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    call = make_call_record(db, status=source, status_changed_at=long_ago)

    response = post(
        robot_client,
        call.id,
        step="GENAI",
        status="FAIL",
        stage="GENAI",
        message="응답 형식 오류, 재시도 3회 소진",
        orchestrator_job_id="job-7",
    )

    assert response.status_code == 201
    assert response.json() == {"call_id": call.id, "status": "FAILED"}
    db.refresh(call)
    assert call.status == S.FAILED
    assert call.status_changed_at > long_ago
    (log,) = logs(db, call.id)  # 전이 로그와 실패 로그가 한 행이다
    assert (log.step, log.status) == ("GENAI", "FAIL")
    assert log.orchestrator_job_id == "job-7"
    assert log.message is not None
    assert f"{source} -> FAILED" in log.message
    assert "[GENAI] 응답 형식 오류, 재시도 3회 소진" in log.message


def test_fail_report_without_message_or_stage_still_fails_the_call(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, status=S.QUEUED)

    response = post(robot_client, call.id, step="STT", status="FAIL")

    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"


@pytest.mark.parametrize("stage", ["INPUT", "STT", "PII", "GENAI", "VALIDATION"])
def test_every_stage_of_the_result_schema_is_accepted(
    robot_client: TestClient, db: Session, stage: str
) -> None:
    call = make_call_record(db, status=S.QUEUED)

    response = post(robot_client, call.id, step="STT", status="FAIL", stage=stage, message="x")

    assert response.status_code == 201
    assert f"[{stage}] x" in (logs(db, call.id)[0].message or "")


@pytest.mark.parametrize("source", [S.STORED, S.NEEDS_REVIEW])
def test_fail_after_processing_finished_keeps_status_and_only_logs(
    robot_client: TestClient, db: Session, source: S
) -> None:
    # 엑셀 기입만 실패한 경우: 분석 결과는 이미 저장되어 있으므로 상태를 되돌리지 않는다.
    call = make_call_record(db, status=source)

    response = post(
        robot_client, call.id, step="EXCEL", status="FAIL", message="엑셀 파일이 열려 있음"
    )

    assert response.status_code == 201
    assert response.json() == {"call_id": call.id, "status": source}
    (log,) = logs(db, call.id)
    assert (log.step, log.status) == ("EXCEL", "FAIL")
    db.refresh(call)
    assert call.status == source


def test_repeated_fail_report_on_failed_call_is_logged_not_rejected(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, status=S.QUEUED)
    post(robot_client, call.id, step="STT", status="FAIL")

    again = post(robot_client, call.id, step="STT", status="FAIL")

    assert again.status_code == 201
    assert again.json()["status"] == "FAILED"
    assert len(logs(db, call.id)) == 2


def test_late_fail_from_old_queue_item_after_retry_request_is_409(
    robot_client: TestClient, db: Session
) -> None:
    # 정체 건이 재처리 요청된 뒤, 멈춰 있던 이전 Queue 건이 뒤늦게 FAIL을 보낸다.
    call = make_call_record(db, status=S.RETRY_REQUESTED)

    response = post(robot_client, call.id, step="STT", status="FAIL")

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "RETRY_REQUESTED"
    assert logs(db, call.id) == []
    db.refresh(call)
    assert call.status == S.RETRY_REQUESTED


def test_failed_call_can_then_be_requested_for_retry(robot_client: TestClient, db: Session) -> None:
    from app.services.state_machine import CallStateMachine

    call = make_call_record(db, status=S.STT_DONE)
    post(robot_client, call.id, step="GENAI", status="FAIL", stage="GENAI")

    CallStateMachine(db, stale_threshold_min=30).transition(call.id, S.RETRY_REQUESTED, actor="web")

    db.refresh(call)
    assert call.status == S.RETRY_REQUESTED
    assert call.retry_count == 1


# ------------------------------------------------------------------ 오류


def test_unknown_and_soft_deleted_calls_are_404(robot_client: TestClient, db: Session) -> None:
    deleted = make_call_record(db, deleted_at=datetime.now(UTC))

    assert post(robot_client, 999_999).status_code == 404
    assert post(robot_client, deleted.id).status_code == 404


@pytest.mark.parametrize(
    ("fields", "loc"),
    [
        ({"step": "UNKNOWN"}, "step"),
        ({"step": None}, "step"),
        ({"status": "ERROR"}, "status"),
        ({"status": None}, "status"),
        ({"stage": "NETWORK"}, "stage"),
        ({"message": "가" * 2001}, "message"),
        ({"orchestrator_job_id": "j" * 65}, "orchestrator_job_id"),
    ],
)
def test_invalid_body_is_422_and_changes_nothing(
    robot_client: TestClient, db: Session, fields: dict[str, Any], loc: str
) -> None:
    call = make_call_record(db, status=S.QUEUED)

    response = post(robot_client, call.id, **fields)

    assert response.status_code == 422
    assert any(loc in error["loc"] for error in response.json()["detail"]["errors"])
    assert logs(db, call.id) == []
    db.refresh(call)
    assert call.status == S.QUEUED


def test_invalid_fail_report_does_not_fail_the_call(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.QUEUED)

    response = post(robot_client, call.id, status="FAIL", stage="NETWORK")

    assert response.status_code == 422
    db.refresh(call)
    assert call.status == S.QUEUED


def test_message_is_not_echoed_in_validation_errors(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db)
    secret = "고객이 말한 민감한 내용"

    response = post(robot_client, call.id, step="UNKNOWN", message=secret)

    assert response.status_code == 422
    assert secret not in response.text


def test_unauthenticated_request_is_401_and_logs_nothing(robot_app: FastAPI, db: Session) -> None:
    call = make_call_record(db, status=S.QUEUED)
    client = TestClient(robot_app, client=(ROBOT_IP, 50000))

    response = post(client, call.id, status="FAIL")

    assert response.status_code == 401
    assert logs(db, call.id) == []
    db.refresh(call)
    assert call.status == S.QUEUED
