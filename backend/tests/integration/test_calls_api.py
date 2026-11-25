from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.factories import make_analysis, make_call, make_log, make_transcript

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 23, 5, 30, 5, tzinfo=UTC)


def test_list_calls_end_to_end(api: TestClient, db: Session) -> None:
    call = make_call(db, call_datetime=T0, agent_name="김상담", status="STORED", created_at=T0)
    make_analysis(db, call, category="불만", question_summary="환불 문의")
    make_call(db, deleted_at=T0)

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


def test_list_calls_page_beyond_last_returns_empty_items(api: TestClient, db: Session) -> None:
    make_call(db)

    body = api.get("/api/calls", params={"page": 5}).json()

    assert body["items"] == []
    assert body["total"] == 1


def test_get_call_detail_end_to_end(api: TestClient, db: Session) -> None:
    call = make_call(db)
    make_transcript(db, call)
    make_analysis(db, call, confidence=Decimal("0.857"), raw_json={"x": 1})
    make_log(db, call, created_at=T0)

    response = api.get(f"/api/calls/{call.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"]["segments"][0]["speaker"] == "AGENT"
    assert body["analysis"]["confidence"] == 0.857
    assert "raw_json" not in body["analysis"]
    assert body["processing_log"][0]["created_at"] == "2026-11-23T14:30:05+09:00"


def test_get_call_without_children(api: TestClient, db: Session) -> None:
    call = make_call(db)

    body = api.get(f"/api/calls/{call.id}").json()

    assert body["transcript"] is None
    assert body["analysis"] is None
    assert body["processing_log"] == []


def test_get_deleted_call_is_404(api: TestClient, db: Session) -> None:
    call = make_call(db, deleted_at=T0)

    response = api.get(f"/api/calls/{call.id}")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_list_calls_stale_filter_and_flag(api: TestClient, db: Session) -> None:
    old = datetime.now(UTC) - timedelta(hours=2)
    stale = make_call(db, status="QUEUED", status_changed_at=old)
    fresh = make_call(db, status="QUEUED")
    make_call(db, status="STORED", status_changed_at=old)
    make_call(db, status="QUEUED", status_changed_at=old, deleted_at=old)

    stale_body = api.get("/api/calls", params={"stale": "true"}).json()
    fresh_body = api.get("/api/calls", params={"stale": "false"}).json()

    assert [(i["id"], i["is_stale"]) for i in stale_body["items"]] == [(stale.id, True)]
    assert stale_body["total"] == 1
    assert fresh_body["total"] == 2
    assert fresh.id in {i["id"] for i in fresh_body["items"]}
    assert not any(i["is_stale"] for i in fresh_body["items"])
    assert api.get(f"/api/calls/{stale.id}").json()["is_stale"] is True
