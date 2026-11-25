"""웹 통계 API: `GET /api/stats/summary`, `GET /api/stats/trend`, `GET /api/stats/breakdown`."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_stats_service
from app.schemas.stats import (
    BreakdownBy,
    BreakdownResponse,
    Granularity,
    StatsPeriod,
    StatsSummary,
    TrendResponse,
)
from app.services.stats_service import StatsService

router = APIRouter(prefix="/api/stats", tags=["stats"])

StatsServiceDep = Annotated[StatsService, Depends(get_stats_service)]


@router.get("/summary")
def get_stats_summary(
    period: Annotated[StatsPeriod, Depends()],
    service: StatsServiceDep,
) -> StatsSummary:
    return service.summary(period)


@router.get("/trend")
def get_stats_trend(
    period: Annotated[StatsPeriod, Depends()],
    service: StatsServiceDep,
    granularity: Annotated[Granularity, Query()] = "day",
) -> TrendResponse:
    return service.trend(period, granularity)


@router.get("/breakdown")
def get_stats_breakdown(
    by: Annotated[BreakdownBy, Query()],
    period: Annotated[StatsPeriod, Depends()],
    service: StatsServiceDep,
) -> BreakdownResponse:
    return service.breakdown(period, by)
