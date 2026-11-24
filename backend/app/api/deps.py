"""라우터 공용 의존성: DB 세션, 서비스 주입."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.repositories.call_repository import CallRepository
from app.repositories.stats_repository import StatsRepository
from app.services.call_service import CallService
from app.services.stats_service import StatsService


def get_db(request: Request) -> Iterator[Session]:
    """요청당 세션 하나. 응답 후 닫는다 (커밋은 서비스가 한다)."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


def get_call_service(session: DbSession) -> CallService:
    return CallService(CallRepository(session))


def get_stats_service(session: DbSession) -> StatsService:
    return StatsService(StatsRepository(session))
