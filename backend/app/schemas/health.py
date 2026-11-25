"""헬스 체크 응답 스키마 (O-02). 200·503 모두 이 형식이다 (§3.1 에러 형식의 예외)."""

from enum import StrEnum

from pydantic import BaseModel


class HealthStatus(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"  # 선택 구성요소(inbox)만 실패 → 200
    FAIL = "FAIL"  # 필수 구성요소(DB·음성 저장소) 실패 → 503


class ComponentStatus(StrEnum):
    OK = "OK"
    FAIL = "FAIL"
    DISABLED = "DISABLED"  # 설정으로 꺼짐(INBOX_BACKEND=disabled). 판정에서 제외


class HealthChecks(BaseModel):
    db: ComponentStatus
    audio_storage: ComponentStatus
    inbox: ComponentStatus


class HealthResponse(BaseModel):
    """전체 상태와 구성요소별 상태. 실패 원인은 응답에 없고 로그(`health_check_failed`)에만 있다."""

    status: HealthStatus
    checks: HealthChecks
