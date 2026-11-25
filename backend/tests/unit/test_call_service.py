"""CallService 쓰기 유스케이스 단위 테스트: 가짜 리포지토리·세션으로 DB 없이 확인한다."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import CallRecord
from app.repositories.call_repository import CallRepository
from app.schemas.call import CallUpdateRequest
from app.schemas.common import KST
from app.services.call_service import CallService, FieldChange, apply_changes, history_value

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
    return CallService(cast(CallRepository, repo), cast(Session, session), stale_threshold_min=30)


def _patch(**body: Any) -> CallUpdateRequest:
    return CallUpdateRequest.model_validate(body)


# ---------------------------------------------------------------- 순수 함수


def test_history_value_formats_datetime_as_kst_seconds() -> None:
    assert history_value(T0.replace(microsecond=999_999)) == "2026-11-23T14:30:05+09:00"
    assert history_value(None) is None
    assert history_value("김상담") == "김상담"


def test_apply_changes_sets_only_different_values() -> None:
    target = SimpleNamespace(agent_name="김상담", client_company=None, call_datetime=T0)

    changes = apply_changes(
        target,
        {
            "agent_name": "김상담",
            "client_company": "가나상사",
            "call_datetime": T0.astimezone(KST),  # 같은 순간, 다른 표기
        },
    )

    assert changes == [FieldChange("client_company", None, "가나상사")]
    assert target.client_company == "가나상사"
    assert target.call_datetime is T0


def test_apply_changes_clears_and_formats_datetime() -> None:
    target = SimpleNamespace(agent_name="김상담", call_datetime=T0)
    new_dt = datetime(2026, 11, 24, 9, 0, tzinfo=KST)

    changes = apply_changes(target, {"agent_name": None, "call_datetime": new_dt})

    assert changes == [
        FieldChange("agent_name", "김상담", None),
        FieldChange("call_datetime", "2026-11-23T14:30:05+09:00", "2026-11-24T09:00:00+09:00"),
    ]
    assert target.agent_name is None


# ---------------------------------------------------------------- update_call


def test_update_applies_metadata_records_history_and_commits() -> None:
    call = _record(agent_name=None, call_datetime=None, metadata_incomplete=True)
    repo, session = FakeCallRepository(call), FakeSession()

    detail = _service(repo, session).update_call(
        1, _patch(agent_name="김상담", call_datetime="2026-11-23T14:30", editor="이수정")
    )

    assert repo.locked == [1]
    assert call.agent_name == "김상담"
    assert call.metadata_incomplete is False
    assert repo.history == [
        (1, "agent_name", None, "김상담", "이수정"),
        (1, "call_datetime", None, "2026-11-23T14:30:00+09:00", "이수정"),
    ]
    assert session.commits == 1
    assert detail.agent_name == "김상담"
    assert detail.metadata_incomplete is False
    assert detail.status == "STORED"


def test_update_clearing_agent_marks_incomplete_again() -> None:
    call = _record()
    repo = FakeCallRepository(call)

    _service(repo, FakeSession()).update_call(1, _patch(agent_name=None))

    assert call.metadata_incomplete is True
    assert repo.history == [(1, "agent_name", "김상담", None, None)]


def test_update_client_only_recomputes_stale_flag_without_history_row() -> None:
    # 값은 채워져 있는데 표시가 true로 남아 있던 건도 메타데이터 키가 오면 바로잡는다.
    call = _record(metadata_incomplete=True)
    repo = FakeCallRepository(call)

    _service(repo, FakeSession()).update_call(1, _patch(client_company="가나상사"))

    assert call.metadata_incomplete is False
    assert [row[1] for row in repo.history] == ["client_company"]


def test_update_same_values_records_nothing() -> None:
    repo, session = FakeCallRepository(_record()), FakeSession()

    _service(repo, session).update_call(1, _patch(agent_name="김상담", call_datetime=T0))

    assert repo.history == []
    assert session.commits == 1


def test_update_empty_body_keeps_flag_and_returns_detail() -> None:
    call = _record(metadata_incomplete=True)  # 메타데이터 키가 없으면 재계산하지 않는다
    repo, session = FakeCallRepository(call), FakeSession()

    detail = _service(repo, session).update_call(1, _patch(editor="이수정"))

    assert call.metadata_incomplete is True
    assert repo.history == []
    assert session.commits == 1  # 바뀐 게 없어도 커밋해 잠금을 푼다
    assert detail.id == 1


def test_update_does_not_touch_status() -> None:
    call = _record(status="QUEUED")

    _service(FakeCallRepository(call), FakeSession()).update_call(1, _patch(agent_name="박상담"))

    assert call.status == "QUEUED"
    assert call.status_changed_at == T0


def test_update_missing_call_is_not_found_without_commit() -> None:
    session = FakeSession()

    with pytest.raises(AppError) as exc_info:
        _service(FakeCallRepository(None), session).update_call(1, _patch(agent_name="김상담"))

    assert exc_info.value.code is ErrorCode.NOT_FOUND
    assert session.commits == 0


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


# ---------------------------------------------------------------- 정체 표시


@pytest.mark.parametrize(("status", "minutes", "expected"), [
    ("QUEUED", 31, True),
    ("QUEUED", 29, False),
    ("STORED", 120, False),
])  # fmt: skip
def test_get_call_marks_stale(status: str, minutes: int, expected: bool) -> None:
    changed = datetime.now(UTC) - timedelta(minutes=minutes)
    repo = FakeCallRepository(_record(status=status, status_changed_at=changed))

    detail = _service(repo, FakeSession()).get_call(1)

    assert detail.is_stale is expected
