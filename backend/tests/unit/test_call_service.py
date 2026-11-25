"""CallService 쓰기 유스케이스 단위 테스트: 가짜 리포지토리·세션으로 DB 없이 확인한다."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import CallRecord
from app.repositories.call_repository import CallRepository
from app.services.call_service import CallService, history_value

T0 = datetime(2026, 11, 23, 5, 30, 5, tzinfo=UTC)  # 14:30:05 KST


def _record(**overrides: Any) -> CallRecord:
    values: dict[str, Any] = {
        "id": 1,
        "source_type": "DRIVE",
        "original_name": "a.wav",
        "duration_sec": None,
        "agent_name": "김상담",
        "client_company": None,
        "call_datetime": T0,
        "metadata_incomplete": False,
        "status": "STORED",
        "status_changed_at": T0,
        "retry_count": 0,
        "created_at": T0,
        "deleted_at": None,
        **overrides,
    }
    return CallRecord(**values)  # DB에 넣지 않는 일시적(transient) 객체


class FakeCallRepository:
    def __init__(self, call: CallRecord | None) -> None:
        self.call = call
        self.history: list[tuple[int, str, str | None, str | None, str | None]] = []
        self.locked: list[int] = []

    def lock_call(self, call_id: int) -> CallRecord | None:
        self.locked.append(call_id)
        return self.call

    def get_call(self, call_id: int) -> CallRecord | None:
        return self.call

    def list_logs(self, call_id: int) -> list[Any]:
        return []

    def add_edit_history(
        self, call_id: int, field: str, before: str | None, after: str | None, *, editor: str | None
    ) -> None:
        self.history.append((call_id, field, before, after, editor))


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _service(repo: FakeCallRepository, session: FakeSession) -> CallService:
    return CallService(cast(CallRepository, repo), cast(Session, session))


# ---------------------------------------------------------------- 순수 함수


def test_history_value_formats_datetime_as_kst_seconds() -> None:
    assert history_value(T0.replace(microsecond=999_999)) == "2026-11-23T14:30:05+09:00"
    assert history_value(None) is None
    assert history_value("김상담") == "김상담"


# ---------------------------------------------------------------- delete_call


def test_delete_sets_aware_deleted_at_and_records_history() -> None:
    call = _record(status="QUEUED")
    repo, session = FakeCallRepository(call), FakeSession()
    before = datetime.now(UTC)

    _service(repo, session).delete_call(1, editor="이수정")

    assert call.deleted_at is not None
    assert call.deleted_at.tzinfo is not None
    assert before - timedelta(seconds=1) <= call.deleted_at <= datetime.now(UTC)
    assert call.status == "QUEUED"
    assert repo.history == [(1, "deleted_at", None, history_value(call.deleted_at), "이수정")]
    assert session.commits == 1


def test_delete_without_editor_records_null_editor() -> None:
    repo = FakeCallRepository(_record())

    _service(repo, FakeSession()).delete_call(1)

    assert repo.history[0][4] is None


def test_delete_missing_or_deleted_call_is_not_found_without_commit() -> None:
    session = FakeSession()

    with pytest.raises(AppError) as exc_info:
        _service(FakeCallRepository(None), session).delete_call(1)

    assert exc_info.value.code is ErrorCode.NOT_FOUND
    assert session.commits == 0
