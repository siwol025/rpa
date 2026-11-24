from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.repositories.call_repository import CallRepository
from app.schemas.call import CallListQuery, CallStatus, Category
from app.schemas.common import KST
from tests.integration.factories import make_analysis, make_call, make_log, make_transcript

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 23, 0, 0, tzinfo=UTC)


def _ids(session: Session, **query: Any) -> list[int]:
    rows = CallRepository(session).list_calls(CallListQuery(**query), offset=0, limit=100)
    return [row[0].id for row in rows]


def test_soft_deleted_calls_are_excluded(db_session: Session) -> None:
    alive = make_call(db_session)
    make_call(db_session, deleted_at=T0)
    repo = CallRepository(db_session)

    assert _ids(db_session) == [alive.id]
    assert repo.count_calls(CallListQuery()) == 1


def test_period_filter_uses_kst_day_and_includes_to(db_session: Session) -> None:
    before = make_call(db_session, call_datetime=datetime(2026, 11, 22, 23, 59, 59, tzinfo=KST))
    first = make_call(db_session, call_datetime=datetime(2026, 11, 23, 0, 0, tzinfo=KST))
    last = make_call(db_session, call_datetime=datetime(2026, 11, 24, 23, 59, 59, tzinfo=KST))
    after = make_call(db_session, call_datetime=datetime(2026, 11, 25, 0, 0, tzinfo=KST))
    make_call(db_session, call_datetime=None, metadata_incomplete=True)

    ids = _ids(db_session, from_=date(2026, 11, 23), to=date(2026, 11, 24))

    assert sorted(ids) == [first.id, last.id]
    assert before.id not in ids and after.id not in ids


def test_only_from_or_only_to(db_session: Session) -> None:
    old = make_call(db_session, call_datetime=datetime(2026, 11, 1, 12, 0, tzinfo=KST))
    new = make_call(db_session, call_datetime=datetime(2026, 11, 20, 12, 0, tzinfo=KST))

    assert _ids(db_session, from_=date(2026, 11, 10)) == [new.id]
    assert _ids(db_session, to=date(2026, 11, 10)) == [old.id]


def test_status_and_category_multi_value(db_session: Session) -> None:
    failed = make_call(db_session, status="FAILED")
    review = make_call(db_session, status="NEEDS_REVIEW")
    make_call(db_session, status="STORED")
    complaint = make_call(db_session)
    make_analysis(db_session, complaint, category="불만")
    inquiry = make_call(db_session)
    make_analysis(db_session, inquiry, category="질의")

    status_ids = _ids(db_session, status=[CallStatus.FAILED, CallStatus.NEEDS_REVIEW])
    assert sorted(status_ids) == [failed.id, review.id]
    assert _ids(db_session, category=[Category.COMPLAINT]) == [complaint.id]


def test_agent_and_client_exact_match(db_session: Session) -> None:
    kim = make_call(db_session, agent_name="김상담", client_company="가나상사")
    make_call(db_session, agent_name="김상담2", client_company="가나상사")

    assert _ids(db_session, agent="김상담") == [kim.id]
    assert len(_ids(db_session, client="가나상사")) == 2
    assert _ids(db_session, client="가나") == []


def test_metadata_incomplete_filter(db_session: Session) -> None:
    incomplete = make_call(db_session, metadata_incomplete=True)
    complete = make_call(db_session)

    assert _ids(db_session, metadata_incomplete=True) == [incomplete.id]
    assert _ids(db_session, metadata_incomplete=False) == [complete.id]


def test_keyword_searches_summaries_and_corrected_text(db_session: Session) -> None:
    by_question = make_call(db_session)
    make_analysis(db_session, by_question, question_summary="요금 환불 요청")
    by_action = make_call(db_session)
    make_analysis(db_session, by_action, action_summary="환불 처리 완료")
    by_transcript = make_call(db_session)
    make_transcript(db_session, by_transcript, corrected_text="고객이 환불을 원함")
    only_segments = make_call(db_session)
    make_transcript(
        db_session,
        only_segments,
        segments=[{"speaker": "CUSTOMER", "start_sec": 0, "end_sec": 1, "text": "환불"}],
    )
    make_call(db_session)

    ids = _ids(db_session, q="환불")

    assert sorted(ids) == [by_question.id, by_action.id, by_transcript.id]
    assert CallRepository(db_session).count_calls(CallListQuery(q="환불")) == 3


def test_keyword_is_case_insensitive_and_escapes_wildcards(db_session: Session) -> None:
    upper = make_call(db_session)
    make_analysis(db_session, upper, question_summary="ARS 50% 할인")
    other = make_call(db_session)
    make_analysis(db_session, other, question_summary="ARS 500 할인")

    assert sorted(_ids(db_session, q="ars")) == [upper.id, other.id]
    assert _ids(db_session, q="50%") == [upper.id]
    assert _ids(db_session, q="5_0") == []


def test_default_sort_is_created_at_desc_with_id_tiebreak(db_session: Session) -> None:
    a = make_call(db_session, created_at=T0)
    b = make_call(db_session, created_at=T0)
    c = make_call(db_session, created_at=T0 + timedelta(minutes=1))

    assert _ids(db_session) == [c.id, b.id, a.id]
    assert _ids(db_session, sort="created_at") == [a.id, b.id, c.id]


def test_call_datetime_sort_puts_nulls_last_both_directions(db_session: Session) -> None:
    none = make_call(db_session, call_datetime=None)
    early = make_call(db_session, call_datetime=T0)
    late = make_call(db_session, call_datetime=T0 + timedelta(hours=1))

    assert _ids(db_session, sort="call_datetime") == [early.id, late.id, none.id]
    assert _ids(db_session, sort="-call_datetime") == [late.id, early.id, none.id]


def test_offset_limit_and_count_out_of_range(db_session: Session) -> None:
    for _ in range(3):
        make_call(db_session)
    repo = CallRepository(db_session)

    assert len(repo.list_calls(CallListQuery(), offset=2, limit=2)) == 1
    assert repo.list_calls(CallListQuery(), offset=10, limit=2) == []
    assert repo.count_calls(CallListQuery()) == 3


def test_list_row_has_analysis_columns_or_none(db_session: Session) -> None:
    analysed = make_call(db_session, created_at=T0 + timedelta(minutes=1))
    make_analysis(db_session, analysed, category="불만", question_summary="요약")
    make_call(db_session, created_at=T0)

    rows = CallRepository(db_session).list_calls(CallListQuery(), offset=0, limit=10)

    assert [tuple(row[1:]) for row in rows] == [("불만", "요약", "OPEN"), (None, None, None)]


def test_get_call_excludes_deleted_and_logs_are_ordered(db_session: Session) -> None:
    call = make_call(db_session)
    deleted = make_call(db_session, deleted_at=T0)
    second = make_log(db_session, call, step="QUEUE", created_at=T0 + timedelta(seconds=1))
    first = make_log(db_session, call, step="REGISTER", created_at=T0)
    make_log(db_session, deleted)
    repo = CallRepository(db_session)

    assert repo.get_call(call.id) is call
    assert repo.get_call(deleted.id) is None
    assert repo.get_call(999_999) is None
    assert [log.id for log in repo.list_logs(call.id)] == [first.id, second.id]
