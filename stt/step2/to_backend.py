# -*- coding: utf-8 -*-
"""
STT 결과(schema/call_schema.json, v1.0) → 백엔드 적재용 값 변환 (로봇 → 백엔드)

기준: call_schema.json은 바꾸지 않는다. 백엔드(DB·API)와 다른 부분은 '적재할 때' 이 모듈에서만 변환한다.
      (STT 파이프라인 코드·프롬프트·스키마는 TRAINING/OTHER, customer_question … 을 그대로 쓴다.)

변환 규칙 (백엔드 HM 피드백)
  1. 유형      : DB에는 한글(CHECK: 질의/불만/건의/교육 내용/기타 문의)이 저장되므로 STT의 type_label을 그대로 category로 쓴다.
                 (TRAINING→EDUCATION, OTHER→ETC 는 백엔드가 API 응답에서 변환 — 우리는 코드를 보내지 않는다)
  2. 필드 이름 : customer_question→question_summary, agent_action→action_summary, customer_company→client_company
  3. 통화 시간 : 소수 초 → 정수 초(반올림, .5는 올림). call_record.duration_sec이 Integer
  4. 전사 구간 : 키는 start_sec / end_sec 로 확정(백엔드 협의 완료). STT 값을 그대로 보낸다 — 이름을 바꾸지 않는다
  5. 검토 필요 : STT 판정을 그대로 따른다. status == NEEDS_REVIEW (확신도 0.6 미만 또는 화자 구분 불확실) → needs_review=True.
                 여기서 다시 계산하지 않는다(백엔드 문서의 0.7 기준을 적용하지 않음)
  6. entities  : [{type, value}] 배열 그대로 (백엔드 PR #6에서 같은 배열로 맞춤)

이 모듈은 외부 패키지 없이 동작한다(백엔드 로봇 API 적재 코드로 옮기기 쉽게).
요청 본문 형식은 백엔드 로봇 API(R-07)가 아직 없어서 확정 전이다. 여기서는 저장 대상별로 세 덩어리로 나눠 돌려준다.
  call       → call_record 갱신 값 (duration_sec, client_company, agent_name, call_datetime)
  transcript → transcript 테이블 값 (segments, stt_engine)
  analysis   → analysis 테이블 값 (category, confidence, question_summary, action_summary, follow_up_required,
               entities, needs_review, prompt_version, raw_json)

사용법
  python to_backend.py --in ..\\schema\\sample_success.json
"""
import argparse
import json
import math
import sys

# ======================================================================= 설정
# 2. 필드 이름 매핑 {STT 키: 백엔드 키}
FIELD_MAP = {
    "customer_question": "question_summary",
    "agent_action": "action_summary",
    "customer_company": "client_company",
}

# 1. DB에 저장되는 category 값 (backend/app/models/analysis.py CATEGORIES). STT 코드 → 한글(= type_label)
DB_CATEGORIES = ("질의", "불만", "건의", "교육 내용", "기타 문의")
STT_CODE_TO_LABEL = {"INQUIRY": "질의", "COMPLAINT": "불만", "SUGGESTION": "건의", "TRAINING": "교육 내용", "OTHER": "기타 문의"}

# raw_json(GenAI 원본)에 보관할 STT 분석 필드. 백엔드 컬럼이 없는 summary·sentiment·follow_up·keywords도 여기에 남는다.
RAW_JSON_FIELDS = (
    "type", "type_label", "type_confidence", "customer_company", "customer_question", "agent_action",
    "summary", "sentiment", "follow_up_required", "follow_up", "keywords", "entities",
)


class NotLoadable(ValueError):
    """백엔드에 적재할 수 없는 STT 결과(필수 값 누락·알 수 없는 유형 등)."""


# ======================================================================= 변환 함수
def round_seconds(value):
    """3. 소수 초 → 정수 초. 반올림(0.5는 올림). None은 None. (Python round()는 2.5→2 이므로 쓰지 않는다)"""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or math.isnan(value):
        raise NotLoadable("duration_sec 값이 올바르지 않음: %r" % (value,))
    return int(math.floor(value + 0.5))


def category_of(doc):
    """1. DB에 넣을 category(한글). type_label을 그대로 쓰고, 없으면 type 코드로 찾는다."""
    label = doc.get("type_label")
    if label is None and doc.get("type") is not None:
        label = STT_CODE_TO_LABEL.get(doc["type"])
    if label not in DB_CATEGORIES:
        raise NotLoadable("알 수 없는 유형: type=%r, type_label=%r" % (doc.get("type"), doc.get("type_label")))
    return label


def convert_segments(segments):
    """4. 전사 구간. 키는 speaker / start_sec / end_sec / text 로 확정 — 이름 변환 없이 필요한 키만 복사한다."""
    try:
        return [{"speaker": s["speaker"], "start_sec": s["start_sec"], "end_sec": s["end_sec"], "text": s["text"]}
                for s in segments or []]
    except KeyError as e:
        raise NotLoadable("전사 구간에 필수 키가 없음: %s (speaker/start_sec/end_sec/text 필요)" % e)


def needs_review_of(doc):
    """5. STT 판정을 그대로 따른다 (status == NEEDS_REVIEW). 확신도·화자 조건을 여기서 다시 계산하지 않는다."""
    return doc.get("status") == "NEEDS_REVIEW"


def to_call_update(doc):
    """call_record에 반영할 값. 3(정수 초)·2(client_company)."""
    src = doc.get("source") or {}
    return {
        "duration_sec": round_seconds(src.get("duration_sec")),
        FIELD_MAP["customer_company"]: doc.get("customer_company"),
        "agent_name": doc.get("agent_name"),
        "call_datetime": doc.get("call_datetime"),
    }


def to_transcript_payload(doc):
    tr = doc.get("transcript") or {}
    if not tr.get("segments"):
        return None
    return {
        "segments": convert_segments(tr["segments"]),
        "stt_engine": (doc.get("processing") or {}).get("stt_engine"),
    }


def to_analysis_payload(doc):
    """1·2·5·6 반영. 분석 결과가 없는 건(FAILED)은 None."""
    if doc.get("status") == "FAILED":
        return None
    return {
        "category": category_of(doc),
        "confidence": doc.get("type_confidence"),
        FIELD_MAP["customer_question"]: doc.get("customer_question"),
        FIELD_MAP["agent_action"]: doc.get("agent_action"),
        "follow_up_required": doc.get("follow_up_required"),
        "entities": doc.get("entities"),  # 6. [{type, value}] 배열 그대로
        "needs_review": needs_review_of(doc),
        "prompt_version": (doc.get("processing") or {}).get("prompt_version"),
        "raw_json": {k: doc.get(k) for k in RAW_JSON_FIELDS},
    }


def to_backend(doc):
    """call_schema.json 형식의 STT 결과 한 건 → {call, transcript, analysis, failure}.
    FAILED 건: analysis=None, failure={stage, reason}(로그 API용). 적재 불가 값이면 NotLoadable."""
    if doc.get("schema_version") != "1.0":
        raise NotLoadable("지원하지 않는 schema_version: %r (이 변환은 1.0 기준)" % (doc.get("schema_version"),))
    return {
        "call": to_call_update(doc),
        "transcript": to_transcript_payload(doc),
        "analysis": to_analysis_payload(doc),
        "failure": doc.get("error") if doc.get("status") == "FAILED" else None,
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="call_schema.json 형식 결과 JSON")
    a = ap.parse_args()
    doc = json.load(open(a.inp, encoding="utf-8-sig"))
    print(json.dumps(to_backend(doc), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
