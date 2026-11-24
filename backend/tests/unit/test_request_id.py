import uuid
from collections.abc import Callable

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient


def _assert_uuid4(value: str) -> None:
    assert len(value) == 36
    assert str(uuid.UUID(value, version=4)) == value


def test_generates_uuid4_when_header_missing(client: TestClient) -> None:
    response = client.get("/calls/1")

    _assert_uuid4(response.headers["X-Request-Id"])


def test_reuses_valid_incoming_request_id(client: TestClient) -> None:
    response = client.get("/calls/1", headers={"X-Request-Id": "robot-123-abc"})

    assert response.headers["X-Request-Id"] == "robot-123-abc"


def test_reuses_request_id_at_max_length(client: TestClient) -> None:
    value = "a" * 64

    response = client.get("/calls/1", headers={"X-Request-Id": value})

    assert response.headers["X-Request-Id"] == value


@pytest.mark.parametrize("value", ["a" * 65, "has space", "a_b", "a.b", ""])
def test_replaces_invalid_incoming_request_id(client: TestClient, value: str) -> None:
    response = client.get("/calls/1", headers={"X-Request-Id": value})

    returned = response.headers["X-Request-Id"]
    assert returned != value
    _assert_uuid4(returned)


def test_generated_request_ids_differ_per_request(client: TestClient) -> None:
    first = client.get("/calls/1").headers["X-Request-Id"]
    second = client.get("/calls/1").headers["X-Request-Id"]

    assert first != second


def test_overrides_request_id_set_by_endpoint(build_app: Callable[..., FastAPI]) -> None:
    app = build_app()

    @app.get("/sets-header")
    def sets_header(response: Response) -> None:
        response.headers["X-Request-Id"] = "inner"

    response = TestClient(app).get("/sets-header", headers={"X-Request-Id": "outer"})

    assert response.headers.get_list("X-Request-Id") == ["outer"]
