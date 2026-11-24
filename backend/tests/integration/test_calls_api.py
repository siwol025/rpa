from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.factories import make_analysis, make_call

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 23, 5, 30, 5, tzinfo=UTC)


def test_list_calls_end_to_end(api: TestClient, db_session: Session) -> None:
    call = make_call(
        db_session, call_datetime=T0, agent_name="김상담", status="STORED", created_at=T0
    )
    make_analysis(db_session, call, category="불만", question_summary="환불 문의")
    make_call(db_session, deleted_at=T0)

    response = api.get("/api/calls", params={"q": "환불", "size": 10})

    assert response.status_code == 200
    body = response.json()
    assert (body["page"], body["size"], body["total"]) == (1, 10, 1)
    item = body["items"][0]
    assert item["id"] == call.id
    assert item["call_datetime"] == "2026-11-23T14:30:05+09:00"
    assert item["category"] == "COMPLAINT"
    assert item["action_status"] == "OPEN"
    assert "object_key" not in item


def test_list_calls_page_beyond_last_returns_empty_items(
    api: TestClient, db_session: Session
) -> None:
    make_call(db_session)

    body = api.get("/api/calls", params={"page": 5}).json()

    assert body["items"] == []
    assert body["total"] == 1
