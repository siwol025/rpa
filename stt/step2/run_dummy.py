# -*- coding: utf-8 -*-
"""
더미 CLOVA 응답 → (Step1 파싱) → 마스킹 → 분석(가짜 LLM) → call_schema.json 형식의 최종 JSON

사용법 (키·음성 불필요)
  python run_dummy.py                       # sample_response_1, 2 둘 다 → test\\out\\ 에 저장
  python run_dummy.py --in ..\\test\\sample_response_2.json
  python run_dummy.py --messy               # LLM이 ```json 코드펜스+설명을 붙이는 상황 흉내(전처리 확인)
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "step1"))
import analyze  # noqa: E402
import mask_pii  # noqa: E402
import parse_clova  # noqa: E402

KST = timezone(timedelta(hours=9))


def messy_llm(system, user):
    return "분석 결과입니다.\n```json\n" + analyze.mock_llm(system, user) + "\n```\n도움이 되었길 바랍니다."


def process(resp, file_name, seq, llm=analyze.mock_llm, prompt_version="v1", stt_error=None):
    """stt_error: clova_stt 가 실패했을 때 {"stage","reason"} (예: INPUT/STT). 있으면 resp 는 쓰지 않고 실패 건으로 만든다."""
    now = datetime.now(KST).replace(microsecond=0)
    base = {
        "schema_version": "1.0",
        "call_id": "%s_%03d" % (now.strftime("%Y%m%d_%H%M%S"), seq),
        "source": {"file_name": file_name, "file_path": file_name, "duration_sec": None,
                   "received_at": now.isoformat()},
        "call_datetime": None, "agent_name": None, "customer_company": None,
    }
    proc = {"stt_engine": "clova-speech", "genai_model": "mock-rule-based", "prompt_version": prompt_version,
            "retry_count": 0, "processed_at": now.isoformat()}
    empty = {"type": None, "type_label": None, "type_confidence": None, "customer_question": None,
             "agent_action": None, "summary": None, "follow_up_required": None,
             "follow_up": None, "keywords": [], "entities": []}
    def failed_stt(stage, reason):
        return {**base, "status": "FAILED", "error": {"stage": stage, "reason": reason}, **empty,
                "transcript": {"full_text": None, "segments": [], "speaker_confidence": None},
                "pii": {"masked": False, "counts": {}}, "processing": proc}

    if stt_error:
        return failed_stt(stt_error["stage"], stt_error["reason"])
    try:
        tr = parse_clova.to_transcript(resp)
    except Exception as e:
        return failed_stt("STT", str(e))
    base["source"]["duration_sec"] = tr["segments"][-1]["end_sec"]
    masked, pii = mask_pii.mask_transcript(tr)
    result, err, retries = analyze.analyze(masked["full_text"], llm=llm)
    proc["retry_count"] = retries
    if err:
        return {**base, "status": "FAILED", "error": err, **empty, "transcript": masked, "pii": pii, "processing": proc}
    status = "NEEDS_REVIEW" if (result["type_confidence"] < 0.6 or masked["speaker_confidence"] == "LOW") else "SUCCESS"
    return {**base, "status": status, "error": None, **result, "type_label": analyze.TYPES[result["type"]],
            "customer_company": result["customer_company"], "transcript": masked, "pii": pii, "processing": proc}


def validate_schema(doc):
    try:
        from jsonschema import Draft7Validator
    except ImportError:
        return None
    schema = json.load(open(os.path.join(ROOT, "schema", "call_schema.json"), encoding="utf-8"))
    return [e.message for e in Draft7Validator(schema).iter_errors(doc)]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", action="append", help="CLOVA 응답 JSON (여러 번 지정 가능)")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "test", "out"))
    ap.add_argument("--messy", action="store_true")
    a = ap.parse_args()
    files = a.inp or [os.path.join(ROOT, "test", "sample_response_%d.json" % i) for i in (1, 2)]
    os.makedirs(a.out_dir, exist_ok=True)
    for i, f in enumerate(files, 1):
        resp = json.load(open(f, encoding="utf-8"))
        doc = process(resp, os.path.basename(f), i, llm=messy_llm if a.messy else analyze.mock_llm)
        errs = validate_schema(doc)
        out = os.path.join(a.out_dir, re.sub(r"\.json$", "", os.path.basename(f)) + "_result.json")
        json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("%s → %s | status=%s type=%s(%s) pii=%s retry=%d | 스키마 %s" % (
            os.path.basename(f), os.path.basename(out), doc["status"], doc["type"], doc["type_confidence"],
            {k: v for k, v in doc["pii"]["counts"].items() if v}, doc["processing"]["retry_count"],
            "검증 생략(jsonschema 없음)" if errs is None else ("통과" if not errs else "위반: %s" % errs)))


if __name__ == "__main__":
    main()
