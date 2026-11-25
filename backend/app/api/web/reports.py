"""웹 보고서 API: `GET /api/reports/excel` (기간 지정 엑셀 보고서)."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_report_service
from app.schemas.report import ReportPeriod
from app.services.report_service import ReportService, report_file_name

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get(
    "/excel",
    response_class=Response,
    responses={200: {"content": {XLSX_MEDIA_TYPE: {}}, "description": "엑셀 보고서 파일"}},
)
def download_excel_report(
    period: Annotated[ReportPeriod, Depends()],
    service: Annotated[ReportService, Depends(get_report_service)],
) -> Response:
    """기간 안의 상담을 RPA 파트 보고서 양식에 채워 내려준다. 피벗·차트는 열 때 갱신된다."""
    content = service.build(period)
    # 비 ASCII 파일명은 filename*(RFC 5987)로, 구형 클라이언트용 ASCII 이름도 함께 준다.
    ascii_name = f"report_{period.start:%Y%m%d}-{period.end:%Y%m%d}.xlsx"
    disposition = (
        f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(report_file_name(period))}"
    )
    return Response(
        content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": disposition, "Cache-Control": "no-store"},
    )
