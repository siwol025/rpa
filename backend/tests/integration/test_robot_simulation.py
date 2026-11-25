"""R-12 로봇 시뮬레이션: 등록·적재·실패·재처리·409 재등록·정체 복구 (UiPath 없이).

로봇의 호출 순서는 `scripts/simulate_robot.py`(RobotSimulator)가 흉내 낸다.
웹 쪽 동작(재처리 요청, W-05)은 상태 머신을 직접 호출해 대신한다.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CallRecord, ProcessingLog
from app.schemas.call import CallStatus
from app.services.state_machine import CallStateMachine, InvalidTransition
from scripts.simulate_robot import (
    DispatchAction,
    RobotSimulator,
    load_sample,
    make_wav,
)

pytestmark = pytest.mark.integration

S = CallStatus
EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "api" / "robot-examples"


@pytest.fixture
def robot(robot_client: TestClient) -> RobotSimulator:
    return RobotSimulator(robot_client)


def call_of(db: Session, call_id: int) -> CallRecord:
    call = db.get(CallRecord, call_id)
    assert call is not None
    db.refresh(call)
    return call


def log_steps(db: Session, call_id: int) -> list[tuple[str, str]]:
    rows = db.scalars(
        select(ProcessingLog).where(ProcessingLog.call_id == call_id).order_by(ProcessingLog.id)
    )
    return [(row.step, row.status) for row in rows]


def web_retry(db: Session, call_id: int) -> None:
    """W-05(재처리 요청)가 하는 전이. 웹 API가 생기기 전까지 상태 머신을 직접 부른다."""
    CallStateMachine(db, stale_threshold_min=30).transition(call_id, S.RETRY_REQUESTED, actor="web")


# ------------------------------------------------------------------ 정상 흐름


def test_success_flow_register_queue_transcript_analysis(
    robot: RobotSimulator, robot_client: TestClient, db: Session
) -> None:
    dispatched = robot.dispatch(make_wav("success"))
    assert dispatched.action is DispatchAction.QUEUED
    assert robot.status(dispatched.call_id) == "QUEUED"

    result = robot.perform(dispatched.call_id, load_sample("case01_success"))

    assert result.status_code == 200
    assert result.json() == {"call_id": dispatched.call_id, "status": "STORED"}
    assert log_steps(db, dispatched.call_id) == [
        ("REGISTER", "SUCCESS"),
        ("QUEUE", "SUCCESS"),
        ("STT", "SUCCESS"),
        ("STORE", "SUCCESS"),
    ]
    detail = robot_client.get(f"/api/calls/{dispatched.call_id}").json()
    assert detail["status"] == "STORED"
    assert detail["analysis"]["category"] == "COMPLAINT"
    assert len(detail["transcript"]["segments"]) == 2
    assert detail["metadata_incomplete"] is False


def test_needs_review_flow_ends_in_needs_review_then_web_review_completes_it(
    robot: RobotSimulator, db: Session
) -> None:
    call_id = robot.dispatch(make_wav("review")).call_id

    result = robot.perform(call_id, load_sample("case02_needs_review"))

    assert result.json()["status"] == "NEEDS_REVIEW"
    CallStateMachine(db, stale_threshold_min=30).transition(call_id, S.STORED, actor="web")
    assert call_of(db, call_id).status == S.STORED


def test_missing_metadata_is_registered_and_still_processed(
    robot: RobotSimulator, robot_client: TestClient
) -> None:
    dispatched = robot.dispatch(make_wav("nometa"), agent_name=None, call_datetime=None)

    robot.perform(dispatched.call_id, load_sample("case05_null_fields"))

    detail = robot_client.get(f"/api/calls/{dispatched.call_id}").json()
    assert detail["status"] == "STORED"
    assert detail["metadata_incomplete"] is True
    assert detail["agent_name"] is None


# ------------------------------------------------------------------ 실패와 재처리


def test_failure_flow_reports_fail_and_call_becomes_failed(
    robot: RobotSimulator, db: Session
) -> None:
    call_id = robot.dispatch(make_wav("failed")).call_id

    result = robot.perform(call_id, load_sample("case03_failed"))

    assert result.status_code == 201
    assert result.json() == {"call_id": call_id, "status": "FAILED"}
    assert log_steps(db, call_id)[-1] == ("STT", "FAIL")


def test_failed_call_is_retried_and_new_result_replaces_the_old(
    robot: RobotSimulator, robot_client: TestClient, db: Session
) -> None:
    call_id = robot.dispatch(make_wav("retry")).call_id
    robot.perform(call_id, load_sample("case03_failed"))
    web_retry(db, call_id)
    assert call_of(db, call_id).status == S.RETRY_REQUESTED

    # Dispatcher가 다음 주기에 다시 Queue에 넣고, Performer가 다시 처리한다.
    assert robot.queue(call_id).status_code == 200
    robot.perform(call_id, load_sample("case01_success"))

    call = call_of(db, call_id)
    assert call.status == S.STORED
    assert call.retry_count == 1
    assert robot_client.get(f"/api/calls/{call_id}").json()["analysis"]["category"] == "COMPLAINT"


def test_stored_call_can_be_reprocessed_and_result_is_overwritten(
    robot: RobotSimulator, robot_client: TestClient, db: Session
) -> None:
    call_id = robot.dispatch(make_wav("reprocess")).call_id
    robot.perform(call_id, load_sample("case01_success"))
    web_retry(db, call_id)
    robot.queue(call_id)

    # case04: 같은 건을 새 프롬프트(v1.3)로 다시 분석한 결과
    result = robot.perform(call_id, load_sample("case04_duplicate_update"))

    assert result.json()["status"] == "STORED"
    detail = robot_client.get(f"/api/calls/{call_id}").json()
    assert detail["analysis"]["follow_up_required"] is False
    assert call_of(db, call_id).retry_count == 1


def test_excel_failure_after_storing_keeps_status_and_only_logs(
    robot: RobotSimulator, db: Session
) -> None:
    call_id = robot.dispatch(make_wav("excel")).call_id
    robot.perform(call_id, load_sample("case01_success"))

    result = robot.report_failure(
        call_id, step="EXCEL", stage="VALIDATION", reason="엑셀이 열려 있음"
    )

    assert result.status_code == 201
    assert result.json()["status"] == "STORED"
    assert log_steps(db, call_id)[-1] == ("EXCEL", "FAIL")


# ------------------------------------------------------------------ 409 재등록


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (S.REGISTERED, DispatchAction.RESUMED),
        (S.QUEUED, DispatchAction.LEAVE),
        (S.STT_DONE, DispatchAction.LEAVE),
        (S.RETRY_REQUESTED, DispatchAction.LEAVE),
        (S.STORED, DispatchAction.MOVE_DONE),
        (S.NEEDS_REVIEW, DispatchAction.MOVE_DONE),
        (S.FAILED, DispatchAction.MOVE_FAILED),
    ],
)
def test_reregistration_action_depends_on_existing_status(
    robot: RobotSimulator,
    db: Session,
    audio_root: Path,
    status: S,
    expected: DispatchAction,
) -> None:
    audio = make_wav(f"dup-{status}")
    first = robot.register(audio)
    call_id = int(first.json()["call_id"])
    call = call_of(db, call_id)
    call.status = status
    db.flush()
    files_before = sorted(audio_root.iterdir())

    again = robot.dispatch(audio)

    assert again.call_id == call_id
    assert again.action is expected
    assert sorted(audio_root.iterdir()) == files_before  # 사본이 늘지 않는다
    assert call_of(db, call_id).status == (
        S.QUEUED if expected is DispatchAction.RESUMED else status
    )


def test_dispatcher_interrupted_before_queueing_resumes_on_next_run(
    robot: RobotSimulator, db: Session
) -> None:
    audio = make_wav("interrupted")
    call_id = int(robot.register(audio).json()["call_id"])  # Queue 추가 전에 로봇이 멈췄다

    resumed = robot.dispatch(audio)  # 다음 실행

    assert resumed.action is DispatchAction.RESUMED
    assert robot.status(call_id) == "QUEUED"
    assert robot.dispatch(audio).action is DispatchAction.LEAVE  # 그다음은 건드리지 않는다


# ------------------------------------------------------------------ 정체 건 복구


def test_stuck_call_is_recovered_and_late_calls_from_old_queue_item_are_rejected(
    robot: RobotSimulator, db: Session
) -> None:
    call_id = robot.dispatch(make_wav("stuck")).call_id
    call = call_of(db, call_id)
    call.status_changed_at = datetime.now(UTC) - timedelta(minutes=45)  # 로봇이 멈춰 정체
    db.flush()

    web_retry(db, call_id)  # 정체되어 재처리 요청이 허용된다
    result = call_of(db, call_id)
    assert (result.status, result.retry_count) == (S.RETRY_REQUESTED, 1)

    # 멈춰 있던 이전 Performer가 뒤늦게 깨어나 보내는 요청은 거절된다 (정상 동작).
    late_transcript = robot.put_transcript(call_id, load_sample("case01_success"))
    late_fail = robot.report_failure(call_id, step="STT", stage="STT", reason="늦은 실패 보고")
    assert late_transcript.status_code == 409
    assert late_fail.status_code == 409
    assert call_of(db, call_id).status == S.RETRY_REQUESTED

    # 새 Queue 건이 정상 처리한다.
    assert robot.queue(call_id).status_code == 200
    robot.perform(call_id, load_sample("case01_success"))
    assert call_of(db, call_id).status == S.STORED


def test_call_that_is_not_stuck_cannot_be_retried(robot: RobotSimulator, db: Session) -> None:
    call_id = robot.dispatch(make_wav("busy")).call_id

    with pytest.raises(InvalidTransition):
        web_retry(db, call_id)


# ------------------------------------------------------------------ 재전송 (멱등)


def test_performer_retry_after_lost_response_is_safe(robot: RobotSimulator, db: Session) -> None:
    call_id = robot.dispatch(make_wav("lost-response")).call_id
    result = load_sample("case01_success")

    first = robot.perform(call_id, result)
    again = robot.perform(call_id, result)  # 응답을 못 받아 Queue 재시도로 전체를 다시 보냄

    assert first.status_code == again.status_code == 200
    assert again.json()["status"] == "STORED"
    assert log_steps(db, call_id).count(("STORE", "SUCCESS")) == 1


def test_dispatcher_retry_of_queued_report_with_same_item_is_safe(
    robot: RobotSimulator,
) -> None:
    call_id = int(robot.register(make_wav("queue-twice")).json()["call_id"])

    first = robot.queue(call_id, 4242)
    again = robot.queue(call_id, 4242)

    assert first.status_code == again.status_code == 200


# ------------------------------------------------------------------ RPA 파트에 준 요청 예시


def _example(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    return data


def test_published_request_examples_are_accepted_by_the_api(
    robot: RobotSimulator, robot_client: TestClient, db: Session
) -> None:
    call_id = int(robot.register(make_wav("example")).json()["call_id"])

    queued = robot_client.patch(
        f"/api/robot/calls/{call_id}/status", json=_example("status-queued.json")
    )
    transcript = robot_client.put(
        f"/api/robot/calls/{call_id}/transcript", json=_example("transcript.json")
    )
    step_log = robot_client.post(f"/api/robot/calls/{call_id}/logs", json=_example("log-step.json"))

    assert (queued.status_code, transcript.status_code, step_log.status_code) == (200, 200, 201)
    assert transcript.json()["status"] == "STT_DONE"


def test_published_fail_example_marks_the_call_failed(
    robot: RobotSimulator, robot_client: TestClient, db: Session
) -> None:
    call_id = robot.dispatch(make_wav("example-fail")).call_id

    response = robot_client.post(f"/api/robot/calls/{call_id}/logs", json=_example("log-fail.json"))

    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"


def test_every_published_json_example_is_valid_json() -> None:
    names = sorted(path.name for path in EXAMPLES.glob("*.json"))

    assert names == ["log-fail.json", "log-step.json", "status-queued.json", "transcript.json"]
    for name in names:
        _example(name)
