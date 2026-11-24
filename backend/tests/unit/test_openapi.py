import json
from collections.abc import Callable
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import ErrorCode
from app.main import create_app
from app.schemas.common import (
    DuplicateFileErrorResponse,
    KstDatetime,
    Page,
    PageParams,
    error_responses,
)
from scripts.export_openapi import OPENAPI_PATH, build_openapi


class Row(BaseModel):
    id: int
    at: KstDatetime


def _ref(response: dict[str, Any]) -> str:
    ref: str = response["content"]["application/json"]["schema"]["$ref"]
    return ref.rsplit("/", 1)[-1]


@pytest.fixture
def spec(build_app: Callable[..., FastAPI]) -> dict[str, Any]:
    app = build_app()

    @app.get("/rows")
    def list_rows(params: Annotated[PageParams, Depends()]) -> Page[Row]:
        return Page(items=[], page=params.page, size=params.size, total=0)

    @app.delete(
        "/rows/{row_id}",
        status_code=204,
        responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_STATE_TRANSITION),
    )
    def delete_row(row_id: int) -> None:
        return None

    @app.post("/register", status_code=201, responses=error_responses(ErrorCode.DUPLICATE_FILE))
    def register_row(row: Row) -> Row:
        return row

    return app.openapi()


def test_default_fastapi_validation_schema_is_not_documented(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]

    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas


def test_every_operation_documents_422_and_500_in_error_format(spec: dict[str, Any]) -> None:
    for path in spec["paths"].values():
        for operation in path.values():
            assert _ref(operation["responses"]["422"]) == "ValidationErrorResponse"
            assert _ref(operation["responses"]["500"]) == "ErrorResponse"


def test_error_responses_documents_status_and_codes(spec: dict[str, Any]) -> None:
    responses = spec["paths"]["/rows/{row_id}"]["delete"]["responses"]

    assert set(responses) == {"204", "404", "409", "422", "500"}
    assert _ref(responses["404"]) == "ErrorResponse"
    assert _ref(responses["409"]) == "ErrorResponse"
    assert responses["409"]["description"] == "INVALID_STATE_TRANSITION"


def test_error_responses_merges_codes_with_same_status() -> None:
    responses = error_responses(ErrorCode.DUPLICATE_FILE, ErrorCode.INVALID_STATE_TRANSITION)

    assert list(responses) == [409]
    assert responses[409]["description"] == "DUPLICATE_FILE, INVALID_STATE_TRANSITION"


def test_duplicate_file_documented_with_detail_model(spec: dict[str, Any]) -> None:
    responses = spec["paths"]["/register"]["post"]["responses"]
    detail = spec["components"]["schemas"]["DuplicateFileDetail"]

    assert _ref(responses["409"]) == "DuplicateFileErrorResponse"
    assert set(detail["required"]) == {"existing_id", "status"}


def test_error_code_is_documented_as_enum(spec: dict[str, Any]) -> None:
    assert set(spec["components"]["schemas"]["ErrorCode"]["enum"]) == set(ErrorCode)


def test_page_schema_and_query_params(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/rows"]["get"]
    params = {param["name"]: param["schema"] for param in operation["parameters"]}
    page = spec["components"]["schemas"]["Page_Row_"]

    assert params["page"]["minimum"] == 1
    assert params["page"]["default"] == 1
    assert params["size"]["maximum"] == 100
    assert params["size"]["default"] == 20
    assert set(page["required"]) == {"items", "page", "size", "total"}


def test_kst_datetime_documented_as_date_time(spec: dict[str, Any]) -> None:
    at = spec["components"]["schemas"]["Row"]["properties"]["at"]

    assert at["format"] == "date-time"


def test_operation_id_is_function_name(spec: dict[str, Any]) -> None:
    assert spec["paths"]["/rows"]["get"]["operationId"] == "list_rows"
    assert spec["paths"]["/register"]["post"]["operationId"] == "register_row"


def test_docs_enabled_by_default(build_app: Callable[..., FastAPI]) -> None:
    client = TestClient(build_app())

    for url in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(url).status_code == 200


def test_docs_disabled_hides_docs_but_keeps_schema(build_app: Callable[..., FastAPI]) -> None:
    app = build_app(docs_enabled=False)
    client = TestClient(app)

    for url in ("/docs", "/redoc", "/openapi.json"):
        response = client.get(url)
        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
    assert app.openapi()["info"]["title"] == "Callcenter AI RPA Backend"


def test_operation_ids_are_unique_in_real_app() -> None:
    spec = create_app(Settings(_env_file=None)).openapi()
    ids = [op["operationId"] for path in spec["paths"].values() for op in path.values()]

    assert len(ids) == len(set(ids))


def test_committed_openapi_is_up_to_date() -> None:
    committed = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

    assert committed == build_openapi(), (
        "docs/api/openapi.json이 최신이 아닙니다. "
        "`uv run python -m scripts.export_openapi`로 다시 생성해 함께 커밋하세요."
    )


def test_error_responses_ignores_repeated_codes() -> None:
    responses = error_responses(ErrorCode.DUPLICATE_FILE, ErrorCode.DUPLICATE_FILE)

    assert responses[409]["model"] is DuplicateFileErrorResponse
    assert responses[409]["description"] == "DUPLICATE_FILE"
