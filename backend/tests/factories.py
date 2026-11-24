"""테스트 데이터 팩토리. 필수 컬럼은 기본값으로 채우고 필요한 값만 덮어쓴다.

    call = make_call_record(db, status="QUEUED")
    make_analysis(db, call, category="불만")

세션에 추가하고 flush 까지만 한다 (commit 은 테스트가 결정).
"""

import hashlib
import itertools
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import Analysis, CallRecord, EditHistory, ProcessingLog, Transcript

_seq = itertools.count(1)


def _add[T](db: Session, obj: T) -> T:
    db.add(obj)
    db.flush()
    return obj


def make_call_record(db: Session, **overrides: Any) -> CallRecord:
    n = next(_seq)
    values: dict[str, Any] = {
        "source_type": "DRIVE",
        "source_ref": f"drive-file-{n}",
        "object_key": f"audio/{n}.wav",
        "original_name": f"20261124_1000_홍길동_테스트고객사_{n}.wav",
        "file_hash": hashlib.sha256(f"call-{n}".encode()).hexdigest(),
        "file_size": 1024 * n,
        "agent_name": "홍길동",
        "client_company": "테스트고객사",
        "call_datetime": datetime(2026, 11, 24, 10, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return _add(db, CallRecord(**values))


def make_transcript(db: Session, call: CallRecord, **overrides: Any) -> Transcript:
    values: dict[str, Any] = {
        "call_id": call.id,
        "segments": [
            {
                "speaker": "AGENT",
                "start": 0.0,
                "end": 3.2,
                "text": "안녕하세요, 무엇을 도와드릴까요?",
            },
            {"speaker": "CUSTOMER", "start": 3.5, "end": 6.0, "text": "요금 관련 문의입니다."},
        ],
        "corrected_text": "안녕하세요, 무엇을 도와드릴까요? 요금 관련 문의입니다.",
        "stt_engine": "test-stt",
    }
    values.update(overrides)
    return _add(db, Transcript(**values))


def make_analysis(db: Session, call: CallRecord, **overrides: Any) -> Analysis:
    values: dict[str, Any] = {
        "call_id": call.id,
        "category": "질의",
        "confidence": 0.95,
        "question_summary": "요금제 변경 문의",
        "action_summary": "요금제 안내",
        "raw_json": {"category": "질의", "confidence": 0.95},
    }
    values.update(overrides)
    return _add(db, Analysis(**values))


def make_processing_log(db: Session, call: CallRecord, **overrides: Any) -> ProcessingLog:
    values: dict[str, Any] = {"call_id": call.id, "step": "REGISTER", "status": "SUCCESS"}
    values.update(overrides)
    return _add(db, ProcessingLog(**values))


def make_edit_history(db: Session, call: CallRecord, **overrides: Any) -> EditHistory:
    values: dict[str, Any] = {
        "call_id": call.id,
        "field": "agent_name",
        "before_val": None,
        "after_val": "홍길동",
        "editor": "tester",
    }
    values.update(overrides)
    return _add(db, EditHistory(**values))
