"""라우터 단위 테스트: 실제 ReportService + 가짜 리포지토리로 파라미터·422·응답 헤더 확인."""

import io
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from typing import Any, cast
from urllib.parse import quote

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_report_service
from app.repositories.report_repository import ReportRepository
from app.schemas.common import KST
from app.schemas.report import ReportPeriod
from app.services.report_service import ReportService
from tests.unit.test_report_service import FakeReportRepository, _analysis, _call

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def repo() -> FakeReportRepository:
    return FakeReportRepository([(_call(), _analysis())])


@pytest.fixture
def api(build_app: Callable[..., FastAPI], repo: FakeReportRepository) -> Iterator[TestClient]:
    app = build_app()
    app.dependency_overrides[get_report_service] = lambda: ReportService(
        cast(ReportRepository, repo)
    )
    with TestClient(app) as client:
        yield client


def test_excel_download_returns_filled_workbook(
    api: TestClient, repo: FakeReportRepository
) -> None:
    response = api.get("/api/reports/excel", params={"from": "2026-11-01", "to": "2026-11-30"})

    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX
    name = quote("콜센터_보고서_20261101-20261130.xlsx")
    assert response.headers["content-disposition"] == (
        f"attachment; filename=\"report_20261101-20261130.xlsx\"; filename*=UTF-8''{name}"
    )
    assert response.headers["cache-control"] == "no-store"
    sheet = openpyxl.load_workbook(io.BytesIO(response.content))["통화이력"]
    assert sheet["A2"].value == 1
    assert repo.periods == [ReportPeriod(from_=date(2026, 11, 1), to=date(2026, 11, 30))]


@pytest.mark.parametrize(
    ("params", "loc", "error_type"),
    [
        ({"from": "2026-11-02", "to": "2026-11-01"}, ["query", "from"], "date_range"),
        ({"from": "2025-01-01", "to": "2026-01-02"}, ["query", "to"], "period_too_long"),
        ({"from": "1999-12-31", "to": "2000-01-01"}, ["query", "from"], "greater_than_equal"),
    ],
)
def test_invalid_period_is_422(
    api: TestClient,
    repo: FakeReportRepository,
    params: dict[str, str],
    loc: list[str],
    error_type: str,
) -> None:
    response = api.get("/api/reports/excel", params=params)

    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert [(e["loc"], e["type"]) for e in errors] == [(loc, error_type)]
    assert repo.periods == []


@pytest.fixture
def spec(build_app: Callable[..., FastAPI]) -> dict[str, Any]:
    return build_app().openapi()


def test_missing_period_uses_default_last_366_days(
    api: TestClient, repo: FakeReportRepository
) -> None:
    today = datetime.now(KST).date()

    response = api.get("/api/reports/excel")

    assert response.status_code == 200
    assert repo.periods == [ReportPeriod(from_=today - timedelta(days=365), to=today)]


def test_only_to_fills_from(api: TestClient, repo: FakeReportRepository) -> None:
    assert api.get("/api/reports/excel", params={"to": "2026-11-30"}).status_code == 200
    assert repo.periods == [ReportPeriod(from_=date(2025, 11, 30), to=date(2026, 11, 30))]


def test_openapi_excel(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/api/reports/excel"]["get"]
    params = {p["name"]: p for p in operation["parameters"]}

    assert operation["operationId"] == "download_excel_report"
    assert operation["tags"] == ["reports"]
    assert not params["from"]["required"] and not params["to"]["required"]
    assert set(operation["responses"]["200"]["content"]) == {XLSX}
