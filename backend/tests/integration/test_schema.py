"""C-04 스키마와 C-05 테스트 기반 검증 (실제 PostgreSQL)."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CallRecord
from tests.factories import (
    make_analysis,
    make_call_record,
    make_edit_history,
    make_processing_log,
    make_transcript,
)

pytestmark = pytest.mark.integration


def test_defaults_are_applied(db: Session) -> None:
    call = make_call_record(db)
    db.refresh(call)

    assert call.status == "REGISTERED"
    assert call.retry_count == 0
    assert call.metadata_incomplete is False
    assert call.status_changed_at is not None
    assert call.deleted_at is None


def test_metadata_fields_are_nullable(db: Session) -> None:
    call = make_call_record(db, agent_name=None, call_datetime=None, metadata_incomplete=True)

    assert call.agent_name is None
    assert call.call_datetime is None


def test_relations_load_together(db: Session) -> None:
    call = make_call_record(db)
    make_transcript(db, call)
    make_analysis(db, call)
    make_processing_log(db, call)
    make_edit_history(db, call)
    db.expire_all()

    loaded = db.get(CallRecord, call.id)

    assert loaded is not None
    assert loaded.transcript is not None
    assert loaded.analysis is not None
    assert len(loaded.logs) == 1
    assert len(loaded.edits) == 1


def test_status_check_constraint_rejects_unknown_value(db: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_call_record_status"):
        make_call_record(db, status="ANALYZED")


def test_category_check_constraint_rejects_unknown_value(db: Session) -> None:
    call = make_call_record(db)

    with pytest.raises(IntegrityError, match="ck_analysis_category"):
        make_analysis(db, call, category="없는유형")


def test_file_hash_unique_only_among_non_deleted(db: Session) -> None:
    first = make_call_record(db)

    with pytest.raises(IntegrityError, match="ux_call_hash"), db.begin_nested():
        make_call_record(db, file_hash=first.file_hash)

    # 소프트 삭제된 건과는 같은 해시로 재등록할 수 있다.
    first.deleted_at = first.created_at
    db.flush()
    again = make_call_record(db, file_hash=first.file_hash)
    assert again.id != first.id


def test_pg_trgm_partial_match_search(db: Session) -> None:
    call = make_call_record(db)
    make_analysis(db, call, question_summary="해외 로밍 요금제 변경 문의")

    found = (
        db.execute(
            text("SELECT call_id FROM analysis WHERE question_summary ILIKE :q"),
            {"q": "%로밍%"},
        )
        .scalars()
        .all()
    )

    assert found == [call.id]


def test_rollback_isolates_tests_part1(db: Session) -> None:
    make_call_record(db)
    db.commit()  # 테스트 안의 commit 도 롤백되어야 한다


def test_rollback_isolates_tests_part2(db: Session) -> None:
    assert db.scalars(select(CallRecord)).all() == []
