# -*- coding: utf-8 -*-
"""키·음성 없이 돌리는 자체 테스트:  python test_step1.py"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clova_stt
import parse_clova

ROOT = clova_stt.ROOT
T = os.path.join(ROOT, "test")
ok = os.path.join(T, "dummy_clova_response.json")
failed = os.path.join(T, "dummy_clova_response_failed.json")
empty = os.path.join(T, "dummy_clova_response_empty.json")
passed = 0


def check(name, cond):
    global passed
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)
    passed += 1


# 1. 정상 응답
r = clova_stt.transcribe(dummy_file=ok)
check("정상: success=True", r["success"] and r["error"] is None and r["stt_json"]["result"] == "COMPLETED")

# 2. 실패/빈 응답
r = clova_stt.transcribe(dummy_file=failed)
check("FAILED 응답: stage=STT", (not r["success"]) and r["error"]["stage"] == "STT")
r = clova_stt.transcribe(dummy_file=empty)
check("빈 음성: success=False", (not r["success"]) and "발화" in r["error"]["reason"])

# 3. 입력 오류 (키 미입력 / 파일 없음)
r = clova_stt.transcribe(audio_path="없는파일.m4a")
check("키 미입력 config → INPUT 오류", (not r["success"]) and r["error"]["stage"] == "INPUT")

# 4. UiPath용 run() 은 JSON 문자열
s = clova_stt.run("없는파일.m4a")
check("run()은 JSON 문자열 반환", isinstance(s, str) and json.loads(s)["success"] is False)
check("출력에 Secret Key 문구 미포함", "clova_secret_key" not in s)

# 5. 파싱
resp = json.load(open(ok, encoding="utf-8"))
tr = parse_clova.to_transcript(resp)
check("연속 발화 병합 (8→7개)", len(tr["segments"]) == 7)
check("첫 발화 = AGENT", tr["segments"][0]["speaker"] == "AGENT")
check("두 번째 = CUSTOMER", tr["segments"][1]["speaker"] == "CUSTOMER")
check("병합 텍스트 확인", "어디서 변경하면 되나요?" in tr["segments"][1]["text"])
check("ms→초 변환", tr["segments"][0]["start_sec"] == 0.4 and tr["segments"][1]["end_sec"] == 11.0)
check("확신도 HIGH", tr["speaker_confidence"] == "HIGH")
check("full_text 형식", tr["full_text"].startswith("[상담원] 안녕하세요") and "\n[고객] " in tr["full_text"])

# 6. 화자 라벨이 뒤바뀐 경우 (고객이 먼저 말하는 통화) → 키워드 규칙이 이겨야 함, 확신도 LOW
sw = copy.deepcopy(resp)
sw["segments"] = sw["segments"][1:] + sw["segments"][:1]  # 고객 발화가 맨 앞
tr2 = parse_clova.to_transcript(sw)
check("고객 선발화: 키워드로 상담원 판정", any(x["speaker"] == "AGENT" and "고객센터" in x["text"] for x in tr2["segments"]))
check("고객 선발화: 확신도 LOW", tr2["speaker_confidence"] == "LOW")

# 7. 화자 1명뿐
one = copy.deepcopy(resp)
for s_ in one["segments"]:
    s_["speaker"] = {"label": "1"}
    s_["diarization"] = {"label": "1"}
tr3 = parse_clova.to_transcript(one)
check("화자 1명: UNKNOWN + LOW", tr3["segments"][0]["speaker"] == "UNKNOWN" and tr3["speaker_confidence"] == "LOW")

# 8. call_schema.json 의 transcript 부분 스키마로 검증
try:
    from jsonschema import Draft7Validator
    schema = json.load(open(os.path.join(ROOT, "schema", "call_schema.json"), encoding="utf-8"))
    sub = schema["properties"]["transcript"]
    errs = list(Draft7Validator(sub).iter_errors(tr))
    check("transcript가 call_schema.json 규격에 맞음", not errs)
except ImportError:
    print("SKIP 스키마 검증 (pip install jsonschema 필요)")

print("\n모든 테스트 통과: %d" % passed)

# 9. 녹음 대본 기반 더미 2건 (질의/불만): 인사말 규칙·병합·PII 문자열 포함 확인
for n, pii in (("sample_response_1.json", "hello@example.com"), ("sample_response_2.json", "010-1234-5678")):
    rr = json.load(open(os.path.join(T, n), encoding="utf-8"))
    t = parse_clova.to_transcript(rr)
    check(n + ": 첫 발화=AGENT, HIGH", t["segments"][0]["speaker"] == "AGENT" and t["speaker_confidence"] == "HIGH")
    check(n + ": 연속 발화 병합(세그먼트 수 감소)", len(t["segments"]) < len(rr["segments"]))
    check(n + ": PII 문자열 보존(마스킹 테스트용)", pii in t["full_text"])
    # 라벨 뒤집기: 상담원이 라벨 "2"여도 인사말 규칙으로 상담원 판정
    fl = copy.deepcopy(rr)
    for s_ in fl["segments"]:
        lab = "2" if s_["speaker"]["label"] == "1" else "1"
        s_["speaker"]["label"] = lab
        s_["diarization"]["label"] = lab
    t2 = parse_clova.to_transcript(fl)
    check(n + ": 라벨 뒤집어도 상담원 판정", t2["segments"][0]["speaker"] == "AGENT")
print("\n최종 통과: %d" % passed)
