"""라우터 단위 테스트: 서비스를 가짜로 바꿔 DB 없이 파라미터 검증·응답 형식·OpenAPI를 확인한다."""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_call_service
from app.core.errors import AppError, ErrorCode
from app.schemas.call import CallDetail, CallListItem, CallListQuery, CallStatus, Category, LogStep
from app.schemas.common import Page, PageParams

_DETAIL = CallDetail.model_validate(
    {
        "id": 1,
        "source_type": "WEB",
        "original_name": "a.wav",
        "duration_sec": None,
        "agent_name": "김상담",
        "client_company": None,
        "call_datetime": datetime(2026, 11, 23, 5, 30, tzinfo=UTC),
        "metadata_incomplete": False,
        "status": "REGISTERED",
        "status_changed_at": datetime(2026, 11, 23, 5, 30, tzinfo=UTC),
        "retry_count": 0,
        "created_at": datetime(2026, 11, 23, 5, 30, tzinfo=UTC),
        "transcript": None,
        "analysis": None,
        "processing_log": [],
    }
)


class FakeCallService:
    def __init__(self) -> None:
        self.calls: list[tuple[CallListQuery, PageParams]] = []

    def list_calls(self, query: CallListQuery, page: PageParams) -> Page[CallListItem]:
        self.calls.append((query, page))
        return Page(items=[], page=page.page, size=page.size, total=0)

    def get_call(self, call_id: int) -> CallDetail:
        if call_id == 1:
            return _DETAIL
        raise AppError(ErrorCode.NOT_FOUND)


@pytest.fixture
def fake() -> FakeCallService:
    return FakeCallService()


@pytest.fixture
def api(build_app: Callable[..., FastAPI], fake: FakeCallService) -> Iterator[TestClient]:
    app = build_app()
    app.dependency_overrides[get_call_service] = lambda: fake
    with TestClient(app) as client:
        yield client


def _error_locs(body: dict[str, Any]) -> list[list[str | int]]:
    return [err["loc"] for err in body["detail"]["errors"]]


def test_list_defaults(api: TestClient, fake: FakeCallService) -> None:
    response = api.get("/api/calls")

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "size": 20, "total": 0}
    query, page = fake.calls[0]
    assert query == CallListQuery()
    assert query.sort == "-created_at"
    assert (page.page, page.size) == (1, 20)


def test_list_parses_all_params(api: TestClient, fake: FakeCallService) -> None:
    response = api.get(
        "/api/calls",
        params=[
            ("from", "2026-11-01"),
            ("to", "2026-11-23"),
            ("category", "COMPLAINT"),
            ("category", "INQUIRY"),
            ("agent", "김상담"),
            ("client", "가나상사"),
            ("status", "FAILED"),
            ("status", "NEEDS_REVIEW"),
            ("q", "환불"),
            ("metadata_incomplete", "true"),
            ("sort", "-call_datetime"),
            ("page", "2"),
            ("size", "100"),
        ],
    )

    assert response.status_code == 200
    query, page = fake.calls[0]
    assert query == CallListQuery(
        from_=date(2026, 11, 1),
        to=date(2026, 11, 23),
        category=[Category.COMPLAINT, Category.INQUIRY],
        agent="김상담",
        client="가나상사",
        status=[CallStatus.FAILED, CallStatus.NEEDS_REVIEW],
        q="환불",
        metadata_incomplete=True,
        sort="-call_datetime",
    )
    assert (page.page, page.size) == (2, 100)


@pytest.mark.parametrize(
    ("params", "loc"),
    [
        ({"sort": "id"}, ["query", "sort"]),
        ({"sort": "agent_name"}, ["query", "sort"]),
        ({"size": "101"}, ["query", "size"]),
        ({"page": "0"}, ["query", "page"]),
        ({"status": "DONE"}, ["query", "status", 0]),
        ({"category": "질의"}, ["query", "category", 0]),
        ({"from": "2026/11/01"}, ["query", "from"]),
        ({"from": "1999-12-31"}, ["query", "from"]),
        ({"to": "2101-01-01"}, ["query", "to"]),
        ({"to": "9999-12-31"}, ["query", "to"]),
        ({"q": "가" * 101}, ["query", "q"]),
        ({"metadata_incomplete": "maybe"}, ["query", "metadata_incomplete"]),
        ({"from": "2026-11-02", "to": "2026-11-01"}, ["query", "from"]),
    ],
)
def test_list_invalid_params_return_422(
    api: TestClient, fake: FakeCallService, params: dict[str, str], loc: list[str | int]
) -> None:
    response = api.get("/api/calls", params=params)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert loc in _error_locs(body)
    assert fake.calls == []


def test_date_range_bounds_are_allowed(api: TestClient) -> None:
    params = {"from": "2000-01-01", "to": "2100-12-31"}
    assert api.get("/api/calls", params=params).status_code == 200


def test_q_with_100_chars_is_allowed(api: TestClient) -> None:
    assert api.get("/api/calls", params={"q": "가" * 100}).status_code == 200


def test_unknown_param_stale_is_ignored(api: TestClient, fake: FakeCallService) -> None:
    assert api.get("/api/calls", params={"stale": "true"}).status_code == 200
    assert fake.calls[0][0] == CallListQuery()


def test_get_call_returns_detail(api: TestClient) -> None:
    response = api.get("/api/calls/1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["call_datetime"] == "2026-11-23T14:30:00+09:00"
    assert body["transcript"] is None
    assert body["analysis"] is None
    assert body["processing_log"] == []


def test_get_call_not_found(api: TestClient) -> None:
    response = api.get("/api/calls/2")

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "대상을 찾을 수 없습니다.",
        "detail": None,
    }


@pytest.mark.parametrize("call_id", ["abc", "0", "9223372036854775808"])
def test_get_call_invalid_id_returns_422(api: TestClient, call_id: str) -> None:
    response = api.get(f"/api/calls/{call_id}")

    assert response.status_code == 422
    assert ["path", "call_id"] in _error_locs(response.json())


# ---------------------------------------------------------------- OpenAPI


@pytest.fixture
def spec(build_app: Callable[..., FastAPI]) -> dict[str, Any]:
    return build_app().openapi()


def test_openapi_list_calls(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/api/calls"]["get"]
    params = {p["name"]: p["schema"] for p in operation["parameters"]}

    assert operation["operationId"] == "list_calls"
    assert operation["tags"] == ["calls"]
    assert set(params) == {
        "from", "to", "category", "agent", "client", "status", "q",
        "metadata_incomplete", "sort", "page", "size",
    }  # fmt: skip
    assert params["sort"]["default"] == "-created_at"
    assert set(params["sort"]["enum"]) == {
        "call_datetime", "-call_datetime", "created_at", "-created_at",
        "status_changed_at", "-status_changed_at",
    }  # fmt: skip
    assert params["status"]["anyOf"][0]["type"] == "array"
    assert params["q"]["anyOf"][0]["maxLength"] == 100
    ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/Page_CallListItem_")


def test_openapi_get_call(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/api/calls/{call_id}"]["get"]

    assert operation["operationId"] == "get_call"
    assert set(operation["responses"]) == {"200", "404", "422", "500"}


def test_openapi_enums(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]

    assert set(schemas["CallStatus"]["enum"]) == set(CallStatus)
    assert set(schemas["Category"]["enum"]) == set(Category)
    assert set(schemas["LogStep"]["enum"]) == set(LogStep)
    assert "is_stale" not in schemas["CallListItem"]["properties"]
    assert "processing_log" in schemas["CallDetail"]["required"]
