"""웹 업로드 API 스키마 (W-07)."""

from pydantic import BaseModel


class UploadedFile(BaseModel):
    name: str  # inbox/에 쓴 이름(정규화 후). Dispatcher 등록 시 목록의 original_name이 된다


class UploadResponse(BaseModel):
    """접수 결과. 202 시점에 파일은 이미 inbox/에 있고, 등록·처리는 이후 Dispatcher가 한다."""

    items: list[UploadedFile]
