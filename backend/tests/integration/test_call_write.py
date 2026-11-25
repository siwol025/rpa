"""메타데이터 보정·삭제: 실제 PostgreSQL에서 저장 값·이력·잠금을 확인한다."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import Analysis, CallRecord, EditHistory, ProcessingLog
from app.repositories.call_repository import CallRepository
from app.schemas.common import KST
from app.services.state_machine import CallStateMachine
from tests.integration.factories import make_analysis, make_call, make_transcript

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 23, 5, 30, 5, tzinfo=UTC)  # 14:30:05 KST

HistoryRow = tuple[str, str | None, str | None, str | None]


def _history(session: Session, call_id: int) -> list[HistoryRow]:
    rows = session.scalars(
        select(EditHistory).where(EditHistory.call_id == call_id).order_by(EditHistory.id)
    )
    return [(r.field, r.before_val, r.after_val, r.editor) for r in rows]


# ---------------------------------------------------------------- 리포지토리


def test_lock_call_excludes_deleted(db: Session) -> None:
    alive = make_call(db)
    deleted = make_call(db, deleted_at=T0)
    repo = CallRepository(db)

    assert repo.lock_call(alive.id) is alive
    assert repo.lock_call(deleted.id) is None
    assert repo.lock_call(alive.id + 10_000) is None


def test_lock_call_works_on_call_with_children(db: Session) -> None:
    # 관계를 JOIN하지 않으므로 하위 행 유무와 관계없이 FOR UPDATE가 실행된다.
    call = make_call(db)
    make_transcript(db, call)

    assert CallRepository(db).lock_call(call.id) is call


def test_add_edit_history_uses_db_default_time(db: Session) -> None:
    call = make_call(db)

    CallRepository(db).add_edit_history(call.id, "agent_name", None, "김상담", editor=None)
    db.flush()

    (row,) = db.scalars(select(EditHistory).where(EditHistory.call_id == call.id))
    assert (row.field, row.before_val, row.after_val, row.editor) == (
        "agent_name",
        None,
        "김상담",
        None,
    )
    assert row.edited_at.tzinfo is not None


def test_state_machine_can_transition_after_lock_call(db: Session) -> None:
    # 검토 완료(W-03)가 lock_call 후 같은 트랜잭션에서 상태 머신을 부르는 구조를 미리 확인한다.
    call = make_call(db, status="NEEDS_REVIEW")
    assert CallRepository(db).lock_call(call.id) is call

    CallStateMachine(db, stale_threshold_min=30).transition(call.id, "STORED", actor="web")

    assert call.status == "STORED"


@pytest.fixture
def committed_call(engine: Engine) -> Iterator[int]:
    """다른 연결에서 보이도록 커밋한 건. 끝나면 지운다(롤백 픽스처 `db`을 쓰지 않음)."""
    with Session(engine) as session:
        call_id = make_call(session).id
        session.commit()
    yield call_id
    with Session(engine) as session:
        session.execute(delete(EditHistory).where(EditHistory.call_id == call_id))
        session.execute(delete(CallRecord).where(CallRecord.id == call_id))
        session.commit()


def test_lock_call_blocks_other_transaction(engine: Engine, committed_call: int) -> None:
    with Session(engine) as first, Session(engine) as second:
        assert CallRepository(first).lock_call(committed_call) is not None
        second.connection().exec_driver_sql("SET LOCAL lock_timeout = '200ms'")

        with pytest.raises(OperationalError, match="lock timeout"):
            CallRepository(second).lock_call(committed_call)

        first.rollback()
        second.rollback()


def test_lock_after_other_transaction_deleted_returns_none(
    engine: Engine, committed_call: int
) -> None:
    # 먼저 잠근 쪽이 삭제하고 커밋하면, 기다리던 쪽은 deleted_at 조건에 걸려 None → 404.
    with Session(engine) as first:
        call = CallRepository(first).lock_call(committed_call)
        assert call is not None
        call.deleted_at = T0
        first.commit()

    with Session(engine) as second:
        assert CallRepository(second).lock_call(committed_call) is None


# ---------------------------------------------------------------- PATCH


def test_patch_fills_metadata_and_records_history(api: TestClient, db: Session) -> None:
    call = make_call(db, metadata_incomplete=True, status="NEEDS_REVIEW", status_changed_at=T0)
    make_analysis(db, call, category="불만")

    response = api.patch(
        f"/api/calls/{call.id}",
        json={
            "agent_name": " 김상담 ",
            "client_company": "가나상사",
            "call_datetime": "2026-11-23T14:30",
            "editor": "이수정",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_name"] == "김상담"
    assert body["call_datetime"] == "2026-11-23T14:30:00+09:00"
    assert body["metadata_incomplete"] is False
    assert body["status"] == "NEEDS_REVIEW"
    assert body["analysis"]["category"] == "COMPLAINT"
    assert body == api.get(f"/api/calls/{call.id}").json()
    db.expire_all()
    stored = db.get(CallRecord, call.id)
    assert stored is not None
    assert stored.call_datetime == datetime(2026, 11, 23, 14, 30, tzinfo=KST)
    assert stored.status_changed_at == T0
    assert _history(db, call.id) == [
        ("agent_name", None, "김상담", "이수정"),
        ("client_company", None, "가나상사", "이수정"),
        ("call_datetime", None, "2026-11-23T14:30:00+09:00", "이수정"),
    ]


def test_patch_null_clears_and_marks_incomplete(api: TestClient, db: Session) -> None:
    call = make_call(db, agent_name="김상담", call_datetime=T0, client_company="가나상사")

    body = api.patch(f"/api/calls/{call.id}", json={"call_datetime": None}).json()

    assert body["call_datetime"] is None
    assert body["metadata_incomplete"] is True
    assert body["agent_name"] == "김상담"
    assert body["client_company"] == "가나상사"
    assert _history(db, call.id) == [("call_datetime", "2026-11-23T14:30:05+09:00", None, None)]


def test_patch_same_values_writes_no_history(api: TestClient, db: Session) -> None:
    call = make_call(db, agent_name="김상담", call_datetime=T0)

    response = api.patch(
        f"/api/calls/{call.id}",
        json={"agent_name": "김상담", "call_datetime": "2026-11-23T14:30:05+09:00"},
    )

    assert response.status_code == 200
    assert _history(db, call.id) == []


def test_patch_empty_body_returns_detail_unchanged(api: TestClient, db: Session) -> None:
    call = make_call(db, metadata_incomplete=True)

    response = api.patch(f"/api/calls/{call.id}", json={})

    assert response.status_code == 200
    assert response.json()["metadata_incomplete"] is True
    assert _history(db, call.id) == []


def test_patch_deleted_call_is_404(api: TestClient, db: Session) -> None:
    call = make_call(db, deleted_at=T0)

    response = api.patch(f"/api/calls/{call.id}", json={"agent_name": "김상담"})

    assert response.status_code == 404
    assert _history(db, call.id) == []


def test_patch_with_unknown_key_is_422_and_changes_nothing(api: TestClient, db: Session) -> None:
    call = make_call(db)

    response = api.patch(f"/api/calls/{call.id}", json={"agent_name": "김상담", "status": "STORED"})

    assert response.status_code == 422
    db.expire_all()
    stored = db.get(CallRecord, call.id)
    assert stored is not None
    assert stored.agent_name is None
    assert _history(db, call.id) == []


# ---------------------------------------------------------------- PATCH 분석 수정·검토 완료


def _analysis(session: Session, call_id: int) -> Analysis:
    session.expire_all()
    analysis = session.scalars(select(Analysis).where(Analysis.call_id == call_id)).one()
    return analysis


def _status(session: Session, call_id: int) -> str:
    session.expire_all()
    stored = session.get(CallRecord, call_id)
    assert stored is not None
    return stored.status


def test_patch_analysis_fields_updates_and_records_history(api: TestClient, db: Session) -> None:
    call = make_call(db, status="STORED", status_changed_at=T0)
    make_analysis(db, call, category="질의", question_summary="원래 질문", action_status="OPEN")

    response = api.patch(
        f"/api/calls/{call.id}",
        json={
            "category": "COMPLAINT",
            "question_summary": " 바뀐 질문 ",
            "action_summary": "환불 안내",
            "action_status": "DONE",
            "editor": "이수정",
        },
    )

    assert response.status_code == 200
    analysis = response.json()["analysis"]
    assert analysis["category"] == "COMPLAINT"
    assert analysis["question_summary"] == "바뀐 질문"
    assert analysis["action_summary"] == "환불 안내"
    assert analysis["action_status"] == "DONE"
    assert response.json()["status"] == "STORED"
    assert _analysis(db, call.id).category == "불만"
    assert _history(db, call.id) == [
        ("category", "질의", "불만", "이수정"),
        ("question_summary", "원래 질문", "바뀐 질문", "이수정"),
        ("action_summary", None, "환불 안내", "이수정"),
        ("action_status", "OPEN", "DONE", "이수정"),
    ]


def test_patch_summary_null_clears(api: TestClient, db: Session) -> None:
    call = make_call(db, status="STORED")
    make_analysis(db, call, action_summary="안내")

    body = api.patch(f"/api/calls/{call.id}", json={"action_summary": None}).json()

    assert body["analysis"]["action_summary"] is None
    assert _history(db, call.id) == [("action_summary", "안내", None, None)]


def test_patch_same_analysis_values_writes_no_history(api: TestClient, db: Session) -> None:
    call = make_call(db, status="STORED")
    make_analysis(db, call, category="불만", action_status="OPEN")

    response = api.patch(
        f"/api/calls/{call.id}", json={"category": "COMPLAINT", "action_status": "OPEN"}
    )

    assert response.status_code == 200
    assert _history(db, call.id) == []


def test_patch_analysis_without_analysis_is_409_and_rolls_back(
    api: TestClient, db: Session
) -> None:
    call = make_call(db, status="QUEUED")

    response = api.patch(
        f"/api/calls/{call.id}", json={"agent_name": "김상담", "category": "COMPLAINT"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_STATE_TRANSITION"
    db.expire_all()
    stored = db.get(CallRecord, call.id)
    assert stored is not None
    assert stored.agent_name is None
    assert _history(db, call.id) == []


def test_patch_review_completed_moves_needs_review_to_stored(api: TestClient, db: Session) -> None:
    call = make_call(db, status="NEEDS_REVIEW", status_changed_at=T0)
    make_analysis(db, call, category="질의", needs_review=True)

    response = api.patch(
        f"/api/calls/{call.id}",
        json={"category": "ETC", "review_completed": True, "editor": "이수정"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "STORED"
    assert body["analysis"]["category"] == "ETC"
    assert body["analysis"]["needs_review"] is False
    assert body["status_changed_at"] != "2026-11-23T14:30:05+09:00"
    assert _history(db, call.id) == [
        ("category", "질의", "기타 문의", "이수정"),
        ("status", "NEEDS_REVIEW", "STORED", "이수정"),
    ]
    logs = db.scalars(select(ProcessingLog).where(ProcessingLog.call_id == call.id)).all()
    assert [(log.step, log.status) for log in logs] == [("STORE", "SUCCESS")]
    assert logs[0].message is not None and "web" in logs[0].message


@pytest.mark.parametrize("status", ["STORED", "FAILED"])
def test_patch_review_completed_outside_needs_review_is_409_and_rolls_back(
    api: TestClient, db: Session, status: str
) -> None:
    call = make_call(db, status=status)
    make_analysis(db, call, category="질의")

    response = api.patch(
        f"/api/calls/{call.id}",
        json={"agent_name": "김상담", "category": "ETC", "review_completed": True},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_STATE_TRANSITION"
    assert _status(db, call.id) == status
    assert _analysis(db, call.id).category == "질의"
    assert _history(db, call.id) == []


def test_patch_analysis_edit_keeps_needs_review(api: TestClient, db: Session) -> None:
    call = make_call(db, status="NEEDS_REVIEW")
    make_analysis(db, call, needs_review=True)

    body = api.patch(f"/api/calls/{call.id}", json={"action_status": "DONE"}).json()

    assert body["status"] == "NEEDS_REVIEW"
    assert body["analysis"]["needs_review"] is True


# ---------------------------------------------------------------- DELETE


@pytest.mark.parametrize("status", ["REGISTERED", "QUEUED", "STORED", "FAILED"])
def test_delete_soft_deletes_in_any_status(api: TestClient, db: Session, status: str) -> None:
    call = make_call(db, status=status, status_changed_at=T0)

    response = api.delete(f"/api/calls/{call.id}", params={"editor": "이수정"})

    assert response.status_code == 204
    assert response.content == b""
    db.expire_all()
    stored = db.get(CallRecord, call.id)
    assert stored is not None
    assert stored.deleted_at is not None
    assert (stored.status, stored.status_changed_at) == (status, T0)
    ((field, before, after, editor),) = _history(db, call.id)
    assert (field, before, editor) == ("deleted_at", None, "이수정")
    assert after == stored.deleted_at.astimezone(KST).replace(microsecond=0).isoformat()


def test_deleted_call_disappears_from_reads_and_second_delete_is_404(
    api: TestClient, db: Session
) -> None:
    call = make_call(db, agent_name="김상담", call_datetime=T0)
    make_analysis(db, call)

    assert api.delete(f"/api/calls/{call.id}").status_code == 204

    assert api.get(f"/api/calls/{call.id}").status_code == 404
    assert api.get("/api/calls").json()["total"] == 0
    assert api.get("/api/stats/breakdown", params={"by": "agent"}).json()["items"] == []
    second = api.delete(f"/api/calls/{call.id}")
    assert second.status_code == 404
    assert second.json()["code"] == "NOT_FOUND"
    assert len(_history(db, call.id)) == 1


def test_delete_without_editor_records_null(api: TestClient, db: Session) -> None:
    call = make_call(db)

    assert api.delete(f"/api/calls/{call.id}").status_code == 204

    assert _history(db, call.id)[0][3] is None


def test_delete_unknown_id_is_404(api: TestClient) -> None:
    response = api.delete("/api/calls/999999999")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_same_file_hash_can_be_added_after_delete(db: Session) -> None:
    # ux_call_hash는 deleted_at IS NULL 부분 인덱스 → 삭제 후 같은 해시 행 추가 가능(등록 참고).
    call = make_call(db, file_hash="f" * 64)
    call.deleted_at = T0
    db.flush()

    assert make_call(db, file_hash="f" * 64).id != call.id
