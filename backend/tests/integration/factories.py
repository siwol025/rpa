"""최소 테스트 데이터 헬퍼 (임시 — C-05 팩토리로 대체 예정).

`now()`는 트랜잭션 시작 시각이라 한 테스트 안에서 기본값 `created_at`이 모두 같다.
정렬을 검증할 때는 시각을 직접 넘긴다.
"""

from itertools import count
from typing import Any

from sqlalchemy.orm import Session

from app.models import Analysis, CallRecord, ProcessingLog, Transcript

_seq = count(1)


def make_call(session: Session, **overrides: Any) -> CallRecord:
    n = next(_seq)
    values: dict[str, Any] = {
        "source_type": "DRIVE",
        "object_key": f"audio/{n}.wav",
        "original_name": f"call-{n}.wav",
        "file_hash": f"{n:064x}",
        **overrides,
    }
    call = CallRecord(**values)
    session.add(call)
    session.flush()
    return call


def make_transcript(session: Session, call: CallRecord, **overrides: Any) -> Transcript:
    values: dict[str, Any] = {
        "segments": [{"speaker": "AGENT", "start_sec": 0.0, "end_sec": 1.5, "text": "안녕하세요"}],
        **overrides,
    }
    transcript = Transcript(call_id=call.id, **values)
    session.add(transcript)
    session.flush()
    return transcript


def make_analysis(session: Session, call: CallRecord, **overrides: Any) -> Analysis:
    values: dict[str, Any] = {"category": "질의", "raw_json": {}, **overrides}
    analysis = Analysis(call_id=call.id, **values)
    session.add(analysis)
    session.flush()
    return analysis


def make_log(session: Session, call: CallRecord, **overrides: Any) -> ProcessingLog:
    values: dict[str, Any] = {"step": "REGISTER", "status": "SUCCESS", **overrides}
    log = ProcessingLog(call_id=call.id, **values)
    session.add(log)
    session.flush()
    return log
