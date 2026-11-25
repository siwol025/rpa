"""상담 메타데이터 규칙. 로봇 등록과 웹 보정이 같은 판정을 쓴다."""

from datetime import datetime


def is_metadata_incomplete(agent_name: str | None, call_datetime: datetime | None) -> bool:
    """담당자 또는 통화 일시가 없으면 True. 고객사는 판정에 넣지 않는다.

    입력 단계에서 빈 문자열을 막거나(웹 422) `None`으로 바꾸므로(로봇 등록) `None`만 본다.
    로봇 등록(`robot_service._create_record`)의 인라인 판정과 같은 규칙이다.
    """
    return agent_name is None or call_datetime is None
