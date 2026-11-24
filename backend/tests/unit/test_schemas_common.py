from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app.schemas.common import (
    KST,
    DuplicateFileErrorResponse,
    ErrorResponse,
    KstDatetime,
    Page,
    PageParams,
    ValidationErrorResponse,
)


class Event(BaseModel):
    at: KstDatetime
    ended_at: KstDatetime | None = None


class Item(BaseModel):
    id: int


# ---------------------------------------------------------------- KstDatetime


def test_utc_datetime_serialized_as_kst_seconds() -> None:
    event = Event(at=datetime(2026, 11, 23, 5, 30, 5, 123456, tzinfo=UTC))

    assert event.model_dump(mode="json")["at"] == "2026-11-23T14:30:05+09:00"


def test_naive_input_is_interpreted_as_kst() -> None:
    event = Event.model_validate({"at": "2026-11-23T14:30:05"})

    assert event.at == datetime(2026, 11, 23, 14, 30, 5, tzinfo=KST)


@pytest.mark.parametrize(
    "raw", ["2026-11-23T05:30:05Z", "2026-11-23T14:30:05+09:00", "2026-11-23T06:30:05+01:00"]
)
def test_offset_input_is_respected(raw: str) -> None:
    event = Event.model_validate({"at": raw})

    assert event.model_dump(mode="json")["at"] == "2026-11-23T14:30:05+09:00"


def test_python_mode_dump_keeps_original_value() -> None:
    value = datetime(2026, 11, 23, 5, 30, 5, 123456, tzinfo=UTC)

    assert Event(at=value).model_dump()["at"] == value


def test_nested_list_and_none_serialization() -> None:
    class Wrapper(BaseModel):
        events: list[Event]

    wrapper = Wrapper(events=[Event(at=datetime(2026, 1, 1, tzinfo=UTC))])

    assert wrapper.model_dump(mode="json") == {
        "events": [{"at": "2026-01-01T09:00:00+09:00", "ended_at": None}]
    }


def test_kst_datetime_schema_keeps_date_time_format() -> None:
    expected = {"format": "date-time", "title": "At", "type": "string"}

    assert Event.model_json_schema(mode="validation")["properties"]["at"] == expected
    assert Event.model_json_schema(mode="serialization")["properties"]["at"] == expected


# ---------------------------------------------------------------- Page / PageParams


@pytest.fixture
def page_client(build_app: Callable[..., FastAPI]) -> TestClient:
    app = build_app()

    @app.get("/things")
    def list_things(params: Annotated[PageParams, Depends()]) -> Page[Item]:
        return Page(items=[], page=params.page, size=params.size, total=0)

    @app.get("/offset")
    def get_offset(params: Annotated[PageParams, Depends()]) -> dict[str, int]:
        return {"offset": params.offset}

    return TestClient(app)


def test_page_params_defaults(page_client: TestClient) -> None:
    assert page_client.get("/things").json() == {"items": [], "page": 1, "size": 20, "total": 0}


@pytest.mark.parametrize(("page", "size", "offset"), [(1, 20, 0), (3, 10, 20), (2, 100, 100)])
def test_page_params_offset(page_client: TestClient, page: int, size: int, offset: int) -> None:
    response = page_client.get("/offset", params={"page": page, "size": size})

    assert response.json() == {"offset": offset}


@pytest.mark.parametrize(
    ("query", "loc"),
    [
        ({"page": 0}, "page"),
        ({"page": 10_001}, "page"),
        ({"size": 0}, "size"),
        ({"size": 101}, "size"),
    ],
)
def test_page_params_out_of_range_rejected(
    page_client: TestClient, query: dict[str, int], loc: str
) -> None:
    response = page_client.get("/things", params=query)

    assert response.status_code == 422
    body = ValidationErrorResponse.model_validate(response.json())
    assert [error.loc for error in body.detail.errors] == [["query", loc]]


def test_page_model_requires_all_fields() -> None:
    with pytest.raises(ValidationError):
        Page[Item].model_validate({"items": [], "page": 1, "size": 20})


# ---------------------------------------------------------------- 에러 모델 = 실제 응답


def test_error_response_matches_not_found_body(client: TestClient) -> None:
    body = client.get("/nope").json()

    assert ErrorResponse.model_validate(body).model_dump(mode="json") == body


def test_validation_error_response_matches_422_body(client: TestClient) -> None:
    body = client.post("/items", json={"name": "a", "count": "many"}).json()

    assert ValidationErrorResponse.model_validate(body).model_dump(mode="json") == body


def test_duplicate_file_error_response_matches_409_body(client: TestClient) -> None:
    body = client.get("/app-error").json()

    model = DuplicateFileErrorResponse.model_validate(body)
    assert model.model_dump(mode="json") == body
    assert model.detail.existing_id == 123
