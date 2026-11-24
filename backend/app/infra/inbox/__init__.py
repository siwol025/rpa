"""웹 업로드 대상 inbox/ 어댑터. 설정(INBOX_BACKEND)에 따라 구현체를 고른다."""

from app.core.config import Settings
from app.infra.inbox.base import InboxUnavailableError, InboxWriter
from app.infra.inbox.drive import DriveInboxWriter
from app.infra.inbox.local import LocalInboxWriter

__all__ = ["InboxUnavailableError", "InboxWriter", "create_inbox_writer"]


def create_inbox_writer(settings: Settings) -> InboxWriter | None:
    """disabled면 None (사용처가 503 / 헬스 체크 "disabled"). 외부 호출·파일 생성은 하지 않는다."""
    match settings.inbox_backend:
        case "drive":
            assert settings.drive_inbox_folder_id  # Settings 검증에서 보장
            return DriveInboxWriter(settings.drive_inbox_folder_id)
        case "local":
            return LocalInboxWriter(settings.inbox_local_path)
        case "disabled":
            return None
