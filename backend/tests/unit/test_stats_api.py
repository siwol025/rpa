"""라우터 단위 테스트: 실제 StatsService + 가짜 리포지토리로 DB 없이 파라미터·422·OpenAPI 확인."""

from collections.abc import Callable, Iterator
from datetime import date
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_stats_service
from app.repositories.stats_repository import StatsRepository
from app.schemas.stats import StatsPeriod
from app.services.stats_service import StatsService
from tests.unit.test_stats_service import FakeStatsRepository


@pytest.fixture
def repo() -> FakeStatsRepository:
    return FakeStatsRepository()


@pytest.fixture
def api(build_app: Callable[..., FastAPI], repo: FakeStatsRepository) -> Iterator[TestClient]:
    app = build_app()
    app.dependency_overrides[get_stats_service] = lambda: StatsService(
        cast(StatsRepository, repo), stale_threshold_min=30
    )
    with TestClient(app) as client:
        yield client


def test_trend_defaults(api: TestClient, repo: FakeStatsRepository) -> None:
    response = api.get("/api/stats/trend")

    assert response.status_code == 200
    assert response.json() == {"granularity": "day", "items": []}
    assert repo.calls == [("period", StatsPeriod(), "day")]


def test_trend_parses_params(api: TestClient, repo: FakeStatsRepository) -> None:
    params = {"from": "2026-11-01", "to": "2026-11-30", "granularity": "month"}

    assert api.get("/api/stats/trend", params=params).status_code == 200
    assert repo.calls == [
        ("period", StatsPeriod(from_=date(2026, 11, 1), to=date(2026, 11, 30)), "month")
    ]


def test_breakdown_parses_params(api: TestClient, repo: FakeStatsRepository) -> None:
    response = api.get("/api/stats/breakdown", params={"by": "agent", "from": "2026-11-01"})

    assert response.status_code == 200
    assert response.json() == {"by": "agent", "items": []}
    assert repo.calls == [("dimension", StatsPeriod(from_=date(2026, 11, 1)), "agent")]


@pytest.mark.parametrize(
    ("path", "params", "loc", "error_type"),
    [
        ("/api/stats/trend", {"granularity": "year"}, ["query", "granularity"], "literal_error"),
        ("/api/stats/trend", {"granularity": "DAY"}, ["query", "granularity"], "literal_error"),
        ("/api/stats/trend", {"from": "1999-12-31"}, ["query", "from"], "greater_than_equal"),
        ("/api/stats/trend", {"to": "2101-01-01"}, ["query", "to"], "less_than_equal"),
        (
            "/api/stats/trend",
            {"from": "2026-11-02", "to": "2026-11-01"},
            ["query", "from"],
            "date_range",
        ),
        (
            "/api/stats/trend",
            {"from": "2026-01-01", "to": "2027-02-05"},
            ["query", "from"],
            "range_too_large",
        ),
        ("/api/stats/breakdown", {}, ["query", "by"], "missing"),
        ("/api/stats/breakdown", {"by": "category"}, ["query", "by"], "literal_error"),
        (
            "/api/stats/breakdown",
            {"by": "agent", "from": "2026-11-02", "to": "2026-11-01"},
            ["query", "from"],
            "date_range",
        ),
    ],
)
def test_invalid_params_return_422(
    api: TestClient,
    repo: FakeStatsRepository,
    path: str,
    params: dict[str, str],
    loc: list[str],
    error_type: str,
) -> None:
    response = api.get(path, params=params)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert {"loc": loc, "type": error_type} in [
        {"loc": e["loc"], "type": e["type"]} for e in body["detail"]["errors"]
    ]
    assert repo.calls == []


def test_trend_400_days_is_allowed(api: TestClient) -> None:
    params = {"from": "2026-01-01", "to": "2027-02-04"}
    assert api.get("/api/stats/trend", params=params).status_code == 200


# ---------------------------------------------------------------- OpenAPI


@pytest.fixture
def spec(build_app: Callable[..., FastAPI]) -> dict[str, Any]:
    return build_app().openapi()


def test_openapi_trend(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/api/stats/trend"]["get"]
    params = {p["name"]: p for p in operation["parameters"]}

    assert operation["operationId"] == "get_stats_trend"
    assert operation["tags"] == ["stats"]
    assert set(params) == {"from", "to", "granularity"}
    assert params["granularity"]["schema"]["enum"] == ["day", "week", "month"]
    assert params["granularity"]["schema"]["default"] == "day"
    assert not params["from"]["required"]
    point = spec["components"]["schemas"]["TrendPoint"]["properties"]["period"]
    assert point["format"] == "date"


def test_openapi_breakdown(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/api/stats/breakdown"]["get"]
    params = {p["name"]: p for p in operation["parameters"]}
    schemas = spec["components"]["schemas"]

    assert operation["operationId"] == "get_stats_breakdown"
    assert operation["tags"] == ["stats"]
    assert params["by"]["required"] is True
    assert params["by"]["schema"]["enum"] == ["agent", "client"]
    assert set(schemas["CategoryCounts"]["required"]) == {
        "INQUIRY", "COMPLAINT", "SUGGESTION", "EDUCATION", "ETC",
    }  # fmt: skip
    assert set(schemas["BreakdownItem"]["required"]) == {"name", "count", "by_category"}


def test_summary_defaults(api: TestClient, repo: FakeStatsRepository) -> None:
    response = api.get("/api/stats/summary")

    zero = {"INQUIRY": 0, "COMPLAINT": 0, "SUGGESTION": 0, "EDUCATION": 0, "ETC": 0}
    assert response.status_code == 200
    assert response.json() == {
        "total": 0,
        "by_category": zero,
        "action_open": 0,
        "needs_review": 0,
        "metadata_incomplete": 0,
        "failed": 0,
        "stale": 0,
    }
    assert repo.calls == [("summary", StatsPeriod(), 30)]


def test_summary_from_after_to_is_422(api: TestClient, repo: FakeStatsRepository) -> None:
    response = api.get("/api/stats/summary", params={"from": "2026-11-02", "to": "2026-11-01"})

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["type"] == "date_range"
    assert repo.calls == []


def test_openapi_summary(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/api/stats/summary"]["get"]
    params = {p["name"] for p in operation["parameters"]}

    assert operation["operationId"] == "get_stats_summary"
    assert operation["tags"] == ["stats"]
    assert params == {"from", "to"}
    assert set(spec["components"]["schemas"]["StatsSummary"]["required"]) == {
        "total", "by_category", "action_open", "needs_review",
        "metadata_incomplete", "failed", "stale",
    }  # fmt: skip
