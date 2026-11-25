"""웹 업로드 API: `POST /api/uploads`."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import get_upload_service
from app.core.errors import ErrorCode
from app.schemas.common import error_responses
from app.schemas.upload import UploadResponse
from app.services.upload_service import IncomingFile, UploadService

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

UploadServiceDep = Annotated[UploadService, Depends(get_upload_service)]


@router.post(
    "",
    status_code=202,
    responses=error_responses(
        ErrorCode.BAD_REQUEST,
        ErrorCode.PAYLOAD_TOO_LARGE,
        ErrorCode.UNSUPPORTED_MEDIA,
        ErrorCode.INBOX_UNAVAILABLE,
    ),
)
def upload_files(
    files: Annotated[list[UploadFile], File()],
    service: UploadServiceDep,
) -> UploadResponse:
    # def(동기): InboxWriter.write는 블로킹(Drive 최악 약 3분)이라 워커 스레드에서 돌린다.
    return service.upload([IncomingFile(file.filename, file.file) for file in files])
