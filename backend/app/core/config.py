"""환경 변수 설정 (pydantic-settings)."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """공통 모듈이 쓰는 설정. 각 기능은 필요한 필드를 여기에 추가한다."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    max_upload_mb: int = Field(default=100, gt=0)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    docs_enabled: bool = True
    # 개발용 기본값(.env.example과 같음). 운영은 .env의 DATABASE_URL로 덮는다.
    database_url: str = "postgresql+psycopg://callcenter:callcenter@localhost:5433/callcenter"
    # 웹 업로드 대상. 기본 disabled라 .env 없는 테스트·OpenAPI 내보내기는 외부 의존이 없다.
    # 키 파일 경로(GOOGLE_APPLICATION_CREDENTIALS)는 google-auth가 직접 읽는다.
    inbox_backend: Literal["drive", "local", "disabled"] = "disabled"
    inbox_local_path: Path = Path("./data/inbox")
    drive_inbox_folder_id: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_comma(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _require_drive_folder(self) -> Self:
        # 설정 누락만 시작을 막는다. 키·인증·네트워크 오류는 업로드·헬스 체크 때 드러난다.
        if self.inbox_backend == "drive" and not self.drive_inbox_folder_id:
            raise ValueError("INBOX_BACKEND=drive 이면 DRIVE_INBOX_FOLDER_ID가 필요합니다")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
