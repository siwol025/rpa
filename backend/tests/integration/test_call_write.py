"""상담 삭제: 실제 PostgreSQL에서 저장 값·이력·잠금을 확인한다."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import CallRecord, EditHistory
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


def test_lock_call_excludes_deleted(db_session: Session) -> None:
    alive = make_call(db_session)
    deleted = make_call(db_session, deleted_at=T0)
    repo = CallRepository(db_session)

    assert repo.lock_call(alive.id) is alive
    assert repo.lock_call(deleted.id) is None
    assert repo.lock_call(alive.id + 10_000) is None


def test_lock_call_works_on_call_with_children(db_session: Session) -> None:
    # 관계를 JOIN하지 않으므로 하위 행 유무와 관계없이 FOR UPDATE가 실행된다.
    call = make_call(db_session)
    make_transcript(db_session, call)

    assert CallRepository(db_session).lock_call(call.id) is call


def test_add_edit_history_uses_db_default_time(db_session: Session) -> None:
    call = make_call(db_session)

    CallRepository(db_session).add_edit_history(call.id, "agent_name", None, "김상담", editor=None)
    db_session.flush()

    (row,) = db_session.scalars(select(EditHistory).where(EditHistory.call_id == call.id))
    assert (row.field, row.before_val, row.after_val, row.editor) == (
        "agent_name",
        None,
        "김상담",
        None,
    )
    assert row.edited_at.tzinfo is not None


def test_state_machine_can_transition_after_lock_call(db_session: Session) -> None:
    # 검토 완료(W-03)가 lock_call 후 같은 트랜잭션에서 상태 머신을 부르는 구조를 미리 확인한다.
    call = make_call(db_session, status="NEEDS_REVIEW")
    assert CallRepository(db_session).lock_call(call.id) is call

    CallStateMachine(db_session, stale_threshold_min=30).transition(call.id, "STORED", actor="web")

    assert call.status == "STORED"


@pytest.fixture
def committed_call(engine: Engine) -> Iterator[int]:
    """다른 연결에서 보이도록 커밋한 건. 끝나면 지운다(롤백 픽스처 `db_session`을 쓰지 않음)."""
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


# ---------------------------------------------------------------- DELETE


@pytest.mark.parametrize("status", ["REGISTERED", "QUEUED", "STORED", "FAILED"])
def test_delete_soft_deletes_in_any_status(
    api: TestClient, db_session: Session, status: str
) -> None:
    call = make_call(db_session, status=status, status_changed_at=T0)

    response = api.delete(f"/api/calls/{call.id}", params={"editor": "이수정"})

    assert response.status_code == 204
    assert response.content == b""
    db_session.expire_all()
    stored = db_session.get(CallRecord, call.id)
    assert stored is not None
    assert stored.deleted_at is not None
    assert (stored.status, stored.status_changed_at) == (status, T0)
    ((field, before, after, editor),) = _history(db_session, call.id)
    assert (field, before, editor) == ("deleted_at", None, "이수정")
    assert after == stored.deleted_at.astimezone(KST).replace(microsecond=0).isoformat()


def test_deleted_call_disappears_from_reads_and_second_delete_is_404(
    api: TestClient, db_session: Session
) -> None:
    call = make_call(db_session, agent_name="김상담", call_datetime=T0)
    make_analysis(db_session, call)

    assert api.delete(f"/api/calls/{call.id}").status_code == 204

    assert api.get(f"/api/calls/{call.id}").status_code == 404
    assert api.get("/api/calls").json()["total"] == 0
    assert api.get("/api/stats/breakdown", params={"by": "agent"}).json()["items"] == []
    second = api.delete(f"/api/calls/{call.id}")
    assert second.status_code == 404
    assert second.json()["code"] == "NOT_FOUND"
    assert len(_history(db_session, call.id)) == 1


def test_delete_without_editor_records_null(api: TestClient, db_session: Session) -> None:
    call = make_call(db_session)

    assert api.delete(f"/api/calls/{call.id}").status_code == 204

    assert _history(db_session, call.id)[0][3] is None


def test_delete_unknown_id_is_404(api: TestClient) -> None:
    response = api.delete("/api/calls/999999999")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_same_file_hash_can_be_added_after_delete(db_session: Session) -> None:
    # ux_call_hash는 deleted_at IS NULL 부분 인덱스 → 삭제 후 같은 해시 행 추가 가능(등록 참고).
    call = make_call(db_session, file_hash="f" * 64)
    call.deleted_at = T0
    db_session.flush()

    assert make_call(db_session, file_hash="f" * 64).id != call.id
