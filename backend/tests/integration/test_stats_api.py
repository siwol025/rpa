from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.schemas.common import KST
from tests.integration.factories import make_analysis, make_call

pytestmark = pytest.mark.integration


def test_trend_end_to_end(api: TestClient, db_session: Session) -> None:
    make_call(db_session, call_datetime=datetime(2026, 11, 18, 9, 0, tzinfo=KST))
    make_call(db_session, call_datetime=datetime(2026, 11, 30, 0, 30, tzinfo=KST))

    params = {"from": "2026-11-16", "to": "2026-12-06", "granularity": "week"}
    response = api.get("/api/stats/trend", params=params)

    assert response.status_code == 200
    assert response.json() == {
        "granularity": "week",
        "items": [
            {"period": "2026-11-16", "count": 1},
            {"period": "2026-11-23", "count": 0},
            {"period": "2026-11-30", "count": 1},
        ],
    }


def test_trend_open_range_too_large_end_to_end(api: TestClient, db_session: Session) -> None:
    make_call(db_session, call_datetime=datetime(2024, 1, 1, 9, 0, tzinfo=KST))
    make_call(db_session, call_datetime=datetime(2026, 11, 23, 9, 0, tzinfo=KST))

    response = api.get("/api/stats/trend")

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["type"] == "range_too_large"
    assert api.get("/api/stats/trend", params={"granularity": "month"}).status_code == 200


def test_breakdown_end_to_end(api: TestClient, db_session: Session) -> None:
    a = make_call(db_session, client_company="가나상사")
    make_analysis(db_session, a, category="불만")
    make_call(db_session, client_company="가나상사")
    make_call(db_session, client_company=None)

    response = api.get("/api/stats/breakdown", params={"by": "client"})

    assert response.status_code == 200
    zero = {"INQUIRY": 0, "COMPLAINT": 0, "SUGGESTION": 0, "EDUCATION": 0, "ETC": 0}
    assert response.json() == {
        "by": "client",
        "items": [
            {"name": "가나상사", "count": 2, "by_category": {**zero, "COMPLAINT": 1}},
            {"name": None, "count": 1, "by_category": zero},
        ],
    }


def test_summary_end_to_end(api: TestClient, db_session: Session) -> None:
    call = make_call(db_session, status="NEEDS_REVIEW")
    make_analysis(db_session, call, category="건의")

    response = api.get("/api/stats/summary")

    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["needs_review"], body["action_open"]) == (1, 1, 1)
    assert body["by_category"]["SUGGESTION"] == 1
