"""R-05 `PATCH /api/robot/calls/{id}/status` (QUEUED 전이, 실제 PostgreSQL)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CallRecord, ProcessingLog
from app.schemas.call import CallStatus
from tests.conftest import ROBOT_IP
from tests.factories import make_call_record

pytestmark = pytest.mark.integration

S = CallStatus


def patch(client: TestClient, call_id: int | str, body: dict[str, Any]) -> Any:
    return client.patch(f"/api/robot/calls/{call_id}/status", json=body)


def queued(queue_item_id: int = 501) -> dict[str, Any]:
    return {"status": "QUEUED", "queue_item_id": queue_item_id}


def logs(db: Session, call_id: int) -> list[ProcessingLog]:
    return list(db.scalars(select(ProcessingLog).where(ProcessingLog.call_id == call_id)))


@pytest.mark.parametrize("source", [S.REGISTERED, S.RETRY_REQUESTED])
def test_queued_from_allowed_states(robot_client: TestClient, db: Session, source: S) -> None:
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    call = make_call_record(db, status=source, status_changed_at=long_ago, retry_count=2)

    response = patch(robot_client, call.id, queued(777))

    assert response.status_code == 200
    assert response.json() == {"call_id": call.id, "status": "QUEUED"}
    db.refresh(call)
    assert call.status == S.QUEUED
    assert call.queue_item_id == 777
    assert call.status_changed_at > long_ago
    assert call.retry_count == 2  # 재처리 횟수는 웹 요청 때 올라가므로 여기서 바꾸지 않는다
    (log,) = logs(db, call.id)
    assert (log.step, log.status) == ("QUEUE", "SUCCESS")
    assert log.message is not None
    assert "queue_item_id=777" in log.message


@pytest.mark.parametrize("source", [S.STT_DONE, S.STORED, S.NEEDS_REVIEW, S.FAILED])
def test_queued_from_other_states_is_409_with_current_status(
    robot_client: TestClient, db: Session, source: S
) -> None:
    call = make_call_record(db, status=source)

    response = patch(robot_client, call.id, queued())

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "INVALID_STATE_TRANSITION"
    assert body["detail"] == {"current_status": source, "requested_status": "QUEUED"}
    db.refresh(call)
    assert call.status == source
    assert call.queue_item_id is None
    assert logs(db, call.id) == []


def test_repeat_with_same_queue_item_is_idempotent(robot_client: TestClient, db: Session) -> None:
    # 응답을 못 받은 Dispatcher가 같은 요청을 다시 보내도 성공해야 한다.
    call = make_call_record(db)

    first = patch(robot_client, call.id, queued(900))
    second = patch(robot_client, call.id, queued(900))

    assert first.status_code == second.status_code == 200
    assert second.json() == {"call_id": call.id, "status": "QUEUED"}
    assert len(logs(db, call.id)) == 1  # 전이는 한 번만 기록된다


def test_repeat_with_different_queue_item_is_409(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db)
    patch(robot_client, call.id, queued(900))

    response = patch(robot_client, call.id, queued(901))

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "QUEUED"
    db.refresh(call)
    assert call.queue_item_id == 900


def test_requeue_after_retry_request(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.RETRY_REQUESTED, queue_item_id=900)

    response = patch(robot_client, call.id, queued(901))

    assert response.status_code == 200
    db.refresh(call)
    assert call.queue_item_id == 901


def test_unknown_call_is_404(robot_client: TestClient) -> None:
    response = patch(robot_client, 999_999, queued())

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_soft_deleted_call_is_404(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, deleted_at=datetime.now(UTC))

    assert patch(robot_client, call.id, queued()).status_code == 404


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"status": "STT_DONE", "queue_item_id": 1}, "status"),
        ({"status": "FAILED", "queue_item_id": 1}, "status"),
        ({"status": "queued", "queue_item_id": 1}, "status"),
        ({"queue_item_id": 1}, "status"),
        ({"status": "QUEUED"}, "queue_item_id"),
        ({"status": "QUEUED", "queue_item_id": 0}, "queue_item_id"),
        ({"status": "QUEUED", "queue_item_id": -5}, "queue_item_id"),
        ({"status": "QUEUED", "queue_item_id": "abc"}, "queue_item_id"),
        ({"status": "QUEUED", "queue_item_id": 2**63}, "queue_item_id"),
    ],
)
def test_invalid_body_is_422_and_changes_nothing(
    robot_client: TestClient, db: Session, body: dict[str, Any], field: str
) -> None:
    call = make_call_record(db)

    response = patch(robot_client, call.id, body)

    assert response.status_code == 422
    assert any(field in error["loc"] for error in response.json()["detail"]["errors"])
    db.refresh(call)
    assert call.status == S.REGISTERED


@pytest.mark.parametrize("call_id", [0, -1, 2**63, "abc"])
def test_invalid_call_id_is_422(robot_client: TestClient, call_id: int | str) -> None:
    assert patch(robot_client, call_id, queued()).status_code == 422


def test_unauthenticated_request_is_401_and_changes_nothing(
    robot_app: FastAPI, db: Session
) -> None:
    call = make_call_record(db)
    client = TestClient(robot_app, client=(ROBOT_IP, 50000))

    response = patch(client, call.id, queued())

    assert response.status_code == 401
    assert db.get(CallRecord, call.id).status == S.REGISTERED  # type: ignore[union-attr]
