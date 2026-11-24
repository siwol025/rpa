"""음성 사본 저장소. 설정(AUDIO_STORAGE_BACKEND)에 따라 구현체를 고른다."""

from app.core.config import Settings
from app.infra.storage.base import (
    AudioNotFoundError,
    AudioStorage,
    ByteRange,
    InvalidKeyError,
    InvalidRangeError,
    StorageError,
)
from app.infra.storage.local import LocalStorage

__all__ = [
    "AudioNotFoundError",
    "AudioStorage",
    "ByteRange",
    "InvalidKeyError",
    "InvalidRangeError",
    "LocalStorage",
    "StorageError",
    "create_audio_storage",
]


def create_audio_storage(settings: Settings) -> AudioStorage:
    """디스크 접근 없이 구현체만 만든다 (폴더는 첫 저장·헬스 체크 때 만든다)."""
    match settings.audio_storage_backend:
        case "local":
            return LocalStorage(settings.audio_storage_root)
