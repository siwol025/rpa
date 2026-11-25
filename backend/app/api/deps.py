"""라우터 공용 의존성: DB 세션, 서비스·어댑터 주입."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.infra.inbox import InboxWriter
from app.infra.storage import AudioStorage
from app.repositories.call_repository import CallRepository
from app.repositories.stats_repository import StatsRepository
from app.services.call_service import CallService
from app.services.robot_service import RobotService
from app.services.stats_service import StatsService
from app.services.upload_service import UploadService


def get_db(request: Request) -> Iterator[Session]:
    """요청당 세션 하나. 응답 후 닫는다 (커밋은 서비스가 한다)."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


def get_inbox_writer(request: Request) -> InboxWriter | None:
    """None이면 웹 업로드 비활성(INBOX_BACKEND=disabled)."""
    writer: InboxWriter | None = request.app.state.inbox_writer
    return writer


def get_call_service(session: DbSession) -> CallService:
    return CallService(CallRepository(session), session)


def get_stats_service(session: DbSession) -> StatsService:
    return StatsService(StatsRepository(session))


def get_audio_storage(request: Request) -> AudioStorage:
    storage: AudioStorage = request.app.state.audio_storage
    return storage


def get_settings_from_app(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_robot_service(
    session: DbSession,
    storage: Annotated[AudioStorage, Depends(get_audio_storage)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> RobotService:
    return RobotService(session, storage, stale_threshold_min=settings.stale_threshold_min)


def get_upload_service(
    writer: Annotated[InboxWriter | None, Depends(get_inbox_writer)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> UploadService:
    return UploadService(writer, settings.allowed_extensions)
