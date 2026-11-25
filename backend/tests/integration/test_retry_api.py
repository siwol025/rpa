"""재처리 요청 `POST /api/calls/{id}/retry` (실제 PostgreSQL)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import Settings
from app.main import create_app
from app.models import CallRecord, EditHistory, ProcessingLog
from app.schemas.call import CallStatus
from tests.factories import make_call_record

pytestmark = pytest.mark.integration

S = CallStatus

# 기본 정체 기준 30분에 여유를 둔 값(분). 정확한 경계는 상태 머신 테스트가 다룬다.
FRESH = 1
STALE = 60


def _ago(minutes: int) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


def _logs(db: Session, call_id: int) -> list[ProcessingLog]:
    return list(
        db.scalars(
            select(ProcessingLog).where(ProcessingLog.call_id == call_id).order_by(ProcessingLog.id)
        )
    )


def _assert_unchanged(db: Session, call: CallRecord, status: CallStatus, retry_count: int) -> None:
    db.refresh(call)
    assert call.status == status
    assert call.retry_count == retry_count
    assert _logs(db, call.id) == []


# ---------------------------------------------------------------- 허용


@pytest.mark.parametrize("src", [S.FAILED, S.NEEDS_REVIEW, S.STORED])
def test_retry_finished_call_is_accepted(api: TestClient, db: Session, src: S) -> None:
    call = make_call_record(db, status=src, status_changed_at=_ago(FRESH))
    before = datetime.now(UTC)

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 202
    assert response.json() == {"call_id": call.id, "status": "RETRY_REQUESTED", "retry_count": 1}
    db.refresh(call)
    assert call.status == S.RETRY_REQUESTED
    assert call.status_changed_at >= before
    logs = _logs(db, call.id)
    assert [(log.step, log.status, log.message) for log in logs] == [
        ("RETRY", "RETRY", f"[web] {src} -> RETRY_REQUESTED")
    ]


@pytest.mark.parametrize("src", [S.REGISTERED, S.QUEUED, S.STT_DONE])
def test_retry_stale_processing_call_is_accepted(api: TestClient, db: Session, src: S) -> None:
    call = make_call_record(db, status=src, status_changed_at=_ago(STALE))

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 202
    assert response.json() == {"call_id": call.id, "status": "RETRY_REQUESTED", "retry_count": 1}
    assert len(_logs(db, call.id)) == 1
    db.refresh(call)
    assert call.status == S.RETRY_REQUESTED


def test_retry_count_accumulates(api: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.FAILED, retry_count=2)

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.json()["retry_count"] == 3
    db.refresh(call)
    assert call.retry_count == 3  # 상태 머신이 한 번만 올린다 (웹에서 다시 올리지 않음)


def test_retry_does_not_write_edit_history(api: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.FAILED)

    api.post(f"/api/calls/{call.id}/retry")

    edits = db.scalars(select(EditHistory).where(EditHistory.call_id == call.id))
    assert list(edits) == []


def test_retry_is_visible_in_call_detail(api: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.STORED)

    api.post(f"/api/calls/{call.id}/retry")
    detail = api.get(f"/api/calls/{call.id}").json()

    assert detail["status"] == "RETRY_REQUESTED"
    assert detail["retry_count"] == 1
    assert detail["processing_log"][-1]["step"] == "RETRY"
    assert detail["processing_log"][-1]["status"] == "RETRY"


# ---------------------------------------------------------------- 거절


@pytest.mark.parametrize("src", [S.REGISTERED, S.QUEUED, S.STT_DONE])
def test_retry_fresh_processing_call_is_409(api: TestClient, db: Session, src: S) -> None:
    call = make_call_record(db, status=src, status_changed_at=_ago(FRESH))

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "INVALID_STATE_TRANSITION"
    assert body["detail"] == {"current_status": src, "requested_status": "RETRY_REQUESTED"}
    _assert_unchanged(db, call, src, 0)


@pytest.mark.parametrize("minutes", [FRESH, STALE], ids=["fresh", "stale"])
def test_retry_already_requested_is_409_even_if_stale(
    api: TestClient, db: Session, minutes: int
) -> None:
    # 임시 가드: 상태 머신은 정체된 RETRY_REQUESTED의 재요청을 허용하지만 이 API는 막는다.
    call = make_call_record(
        db, status=S.RETRY_REQUESTED, status_changed_at=_ago(minutes), retry_count=1
    )

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "current_status": "RETRY_REQUESTED",
        "requested_status": "RETRY_REQUESTED",
    }
    _assert_unchanged(db, call, S.RETRY_REQUESTED, 1)


def test_retry_twice_second_is_409(api: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.FAILED)

    first = api.post(f"/api/calls/{call.id}/retry")
    second = api.post(f"/api/calls/{call.id}/retry")

    assert first.status_code == 202
    assert second.status_code == 409
    db.refresh(call)
    assert call.retry_count == 1
    assert len(_logs(db, call.id)) == 1


def test_retry_missing_call_is_404(api: TestClient) -> None:
    response = api.post("/api/calls/999999999/retry")

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "대상을 찾을 수 없습니다.",
        "detail": None,
    }


def test_retry_deleted_call_is_404(api: TestClient, db: Session) -> None:
    call = make_call_record(db, status=S.FAILED, deleted_at=_ago(FRESH))

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 404
    _assert_unchanged(db, call, S.FAILED, 0)


# ---------------------------------------------------------------- 잠금 읽기 순서 (식별자 맵)


def _change_row_behind_session(db: Session, call_id: int, **values: object) -> None:
    """세션의 식별자 맵을 거치지 않고 행만 바꾼다 (다른 요청이 먼저 커밋한 상황 흉내)."""
    db.connection().execute(update(CallRecord).where(CallRecord.id == call_id).values(**values))


def test_guard_reads_current_row_not_stale_session_object(api: TestClient, db: Session) -> None:
    # 세션 객체는 FAILED지만 DB는 이미 정체된 RETRY_REQUESTED다.
    call = make_call_record(db, status=S.FAILED, retry_count=1)
    _change_row_behind_session(db, call.id, status=S.RETRY_REQUESTED, status_changed_at=_ago(STALE))

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "RETRY_REQUESTED"
    _assert_unchanged(db, call, S.RETRY_REQUESTED, 1)


def test_stale_judgement_uses_current_row_not_stale_session_object(
    api: TestClient, db: Session
) -> None:
    # 세션 객체는 방금 바뀐 QUEUED지만 DB의 status_changed_at은 정체 기준을 넘었다.
    call = make_call_record(db, status=S.QUEUED, status_changed_at=_ago(FRESH))
    _change_row_behind_session(db, call.id, status_changed_at=_ago(STALE))

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 202
    assert response.json()["retry_count"] == 1
    db.refresh(call)
    assert call.status == S.RETRY_REQUESTED


# ---------------------------------------------------------------- 설정


@pytest.fixture
def api_threshold_5(db: Session) -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None, stale_threshold_min=5))
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client


def test_stale_threshold_comes_from_app_settings(
    api: TestClient, api_threshold_5: TestClient, db: Session
) -> None:
    rejected = make_call_record(db, status=S.QUEUED, status_changed_at=_ago(10))
    accepted = make_call_record(db, status=S.QUEUED, status_changed_at=_ago(10))

    assert api.post(f"/api/calls/{rejected.id}/retry").status_code == 409  # 기본 30분
    assert api_threshold_5.post(f"/api/calls/{accepted.id}/retry").status_code == 202  # 5분
