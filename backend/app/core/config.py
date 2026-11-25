"""환경 변수 설정 (pydantic-settings)."""

import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self, get_args

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# 내용(매직 바이트) 판정 규칙이 있는 음성 형식. 형식을 늘릴 때는 판정 규칙과 함께 추가한다.
AudioExtension = Literal["wav", "mp3"]


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
    # 로봇 API(/api/robot/*) 접근 통제 (R-01). 비어 있으면 모든 요청을 거절한다(fail closed).
    # ROBOT_API_KEYS는 쉼표로 2개까지 동시에 허용(키 교체 기간), ROBOT_ALLOWED_IPS는 IP·CIDR 목록.
    robot_api_keys: Annotated[list[str], NoDecode] = Field(default_factory=list)
    robot_allowed_ips: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # 서버 음성 사본 저장소. 운영은 Docker 볼륨(/data/audio)을 가리킨다 (GCS는 X-02에서 추가).
    audio_storage_backend: Literal["local"] = "local"
    audio_storage_root: Path = Path("./data/audio")
    # 이 시간(분)을 넘게 같은 처리 중 상태에 머문 건은 정체로 본다 (R-02 재처리 허용, R-11 감지).
    stale_threshold_min: int = Field(default=30, gt=0)
    # 웹 업로드 허용 확장자(쉼표 구분, 대소문자·앞 점 무시). 판정 규칙이 없는 값이면 시작 실패.
    allowed_extensions: Annotated[list[AudioExtension], NoDecode] = Field(
        default_factory=lambda: list(get_args(AudioExtension)), min_length=1
    )

    @field_validator("cors_origins", "robot_api_keys", "robot_allowed_ips", mode="before")
    @classmethod
    def _split_comma(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("robot_api_keys")
    @classmethod
    def _limit_robot_keys(cls, value: list[str]) -> list[str]:
        if len(value) > 2:
            raise ValueError("ROBOT_API_KEYS는 최대 2개까지 허용합니다 (키 교체용)")
        return value

    @field_validator("robot_allowed_ips")
    @classmethod
    def _validate_robot_ips(cls, value: list[str]) -> list[str]:
        for item in value:
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError:
                raise ValueError(
                    f"ROBOT_ALLOWED_IPS에 올바르지 않은 IP/CIDR가 있습니다: {item}"
                ) from None
        return value

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def _split_extensions(cls, value: object) -> object:
        if isinstance(value, str):
            items = (item.strip().lower().removeprefix(".") for item in value.split(","))
            return [item for item in items if item]
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
