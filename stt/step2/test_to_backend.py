# -*- coding: utf-8 -*-
"""STT 결과 → 백엔드 적재 변환 테스트 (키·음성·백엔드 서버 불필요):  python test_to_backend.py"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import run_dummy
import to_backend as tb

passed = 0


def check(name, cond):
    global passed
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)
    passed += 1


def load(p):
    return json.load(open(os.path.join(ROOT, p), encoding="utf-8"))


ok = load("schema/sample_success.json")      # COMPLAINT, duration 142.6, SUCCESS
bad = load("schema/sample_failed.json")      # FAILED
out = tb.to_backend(ok)
an, call, tr = out["analysis"], out["call"], out["transcript"]

# 1. 유형: type_label(한글)을 그대로 category로
check("1. category = type_label(한글)", an["category"] == "불만")
for code, label in tb.STT_CODE_TO_LABEL.items():
    d = copy.deepcopy(ok); d["type"] = code; d["type_label"] = label
    check("1. %s → %s (DB 한글 값)" % (code, label), tb.to_backend(d)["analysis"]["category"] == label)
d = copy.deepcopy(ok); d["type"] = "TRAINING"; d["type_label"] = None
check("1. type_label이 없으면 type 코드에서 한글 복원(TRAINING→교육 내용)", tb.to_backend(d)["analysis"]["category"] == "교육 내용")
check("1. EDUCATION/ETC 코드는 보내지 않음", "EDUCATION" not in json.dumps(out, ensure_ascii=False) and "ETC" not in json.dumps(out["analysis"]["category"]))
for label in ("교육", "EDUCATION", "TRAINING", ""):
    d = copy.deepcopy(ok); d["type_label"] = label
    try:
        tb.to_backend(d)
        check("1. DB 값이 아닌 type_label 거부: %r" % label, False)
    except tb.NotLoadable:
        check("1. DB 값이 아닌 type_label 거부: %r" % label, True)

# 2. 필드 이름
check("2. question_summary / action_summary", an["question_summary"] == ok["customer_question"] and an["action_summary"] == ok["agent_action"])
check("2. client_company (call_record 쪽)", call["client_company"] == ok["customer_company"] == "○○상사")
check("2. 옛 이름이 전송 값에 없음", not any(k in an or k in call for k in ("customer_question", "agent_action", "customer_company")))
check("2. confidence ← type_confidence", an["confidence"] == ok["type_confidence"])

# 3. 통화 시간 반올림
check("3. 142.6 → 143 (정수)", call["duration_sec"] == 143 and isinstance(call["duration_sec"], int))
for v, exp in ((142.4, 142), (142.5, 143), (0.5, 1), (2.5, 3), (0, 0), (4.2, 4), (59.99, 60), (None, None)):
    check("3. round_seconds(%r) = %r" % (v, exp), tb.round_seconds(v) == exp)
check("3. FAILED 건 4.2 → 4", tb.to_backend(bad)["call"]["duration_sec"] == 4)
for v in (-1, "3", True):
    try:
        tb.round_seconds(v)
        check("3. 잘못된 duration 거부: %r" % (v,), False)
    except tb.NotLoadable:
        check("3. 잘못된 duration 거부: %r" % (v,), True)

# 4. 전사 구간 키 (설정 한 곳)
seg = tr["segments"][0]
check("4. 기본: start_sec/end_sec 유지", set(seg) == {"speaker", "start_sec", "end_sec", "text"} and seg["start_sec"] == 0.4 and seg["end_sec"] == 3.1)
alt = {"start_sec": "start", "end_sec": "end"}
seg2 = tb.to_backend(ok, key_map=alt)["transcript"]["segments"][0]
check("4. 매핑만 바꾸면 start/end로 전환", set(seg2) == {"speaker", "start", "end", "text"} and seg2["start"] == 0.4 and seg2["end"] == 3.1)
tb.SEGMENT_KEY_MAP = alt
check("4. 모듈 설정(SEGMENT_KEY_MAP)을 바꿔도 동일", "start" in tb.to_backend(ok)["transcript"]["segments"][1])
tb.SEGMENT_KEY_MAP = {"start_sec": "start_sec", "end_sec": "end_sec"}
check("4. 값(시간·화자·텍스트)은 변하지 않음", [s["text"] for s in tr["segments"]] == [s["text"] for s in ok["transcript"]["segments"]]
      and [s["speaker"] for s in tr["segments"]] == ["AGENT", "CUSTOMER"])
check("4. 원본 문서는 변경되지 않음", "start_sec" in ok["transcript"]["segments"][0] and "start" not in ok["transcript"]["segments"][0])
check("4. stt_engine 전달", tr["stt_engine"] == "clova-speech")

# 5. 검토 필요: STT 판정 그대로
check("5. SUCCESS → needs_review=False", an["needs_review"] is False)
d = copy.deepcopy(ok); d["status"] = "NEEDS_REVIEW"; d["type_confidence"] = 0.4
check("5. NEEDS_REVIEW(확신도 0.4) → True", tb.to_backend(d)["analysis"]["needs_review"] is True)
d = copy.deepcopy(ok); d["status"] = "NEEDS_REVIEW"; d["type_confidence"] = 0.95; d["transcript"]["speaker_confidence"] = "LOW"
check("5. NEEDS_REVIEW(화자 불확실, 확신도 높음) → True", tb.to_backend(d)["analysis"]["needs_review"] is True)
d = copy.deepcopy(ok); d["type_confidence"] = 0.65
check("5. SUCCESS + 확신도 0.65 → False (0.7 기준을 다시 적용하지 않음)", tb.to_backend(d)["analysis"]["needs_review"] is False)

# 6. entities: 배열 그대로
check("6. entities 배열 그대로", an["entities"] == ok["entities"] and isinstance(an["entities"], list))
d = copy.deepcopy(ok); d["entities"] = []
check("6. 빈 배열은 빈 배열", tb.to_backend(d)["analysis"]["entities"] == [])

# 그 밖의 안전장치
check("raw_json: 백엔드 컬럼이 없는 summary·sentiment·keywords 보존", all(k in an["raw_json"] for k in ("summary", "sentiment", "keywords", "follow_up")))
check("prompt_version 전달", an["prompt_version"] == ok["processing"]["prompt_version"])
fo = tb.to_backend(bad)
check("FAILED: analysis 없음, failure에 사유", fo["analysis"] is None and fo["failure"]["stage"] == "STT" and fo["transcript"] is None)
d = copy.deepcopy(ok); d["schema_version"] = "1.1"
try:
    tb.to_backend(d)
    check("schema_version 1.0이 아니면 거부", False)
except tb.NotLoadable:
    check("schema_version 1.0이 아니면 거부", True)
d = copy.deepcopy(ok); d["type"] = None; d["type_label"] = None
try:
    tb.to_backend(d)
    check("유형이 없는 성공 건 거부", False)
except tb.NotLoadable:
    check("유형이 없는 성공 건 거부", True)

# 실제 파이프라인 결과(더미 응답 2건)도 그대로 변환되는지
T = os.path.join(ROOT, "test")
for i, typ in ((1, "질의"), (2, "불만")):
    resp = json.load(open(os.path.join(T, "sample_response_%d.json" % i), encoding="utf-8"))
    doc = run_dummy.process(resp, "sample_response_%d.json" % i, i)
    o = tb.to_backend(doc)
    check("파이프라인 결과 %d: 변환 성공, category=%s, 정수 duration" % (i, typ), o["analysis"]["category"] == typ and isinstance(o["call"]["duration_sec"], int))

print("\n통과: %d" % passed)
