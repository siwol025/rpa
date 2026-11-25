"""재처리 요청 API 스키마 (W-05)."""

from pydantic import BaseModel

from app.schemas.call import CallStatus


class RetryResult(BaseModel):
    """재처리 요청 접수 결과. 실제 재처리는 다음 Dispatcher 주기에 일어난다."""

    call_id: int
    status: CallStatus
    retry_count: int  # 상태 머신이 올린 값. Dispatcher가 Queue Reference `call_id-retryN`에 쓴다
