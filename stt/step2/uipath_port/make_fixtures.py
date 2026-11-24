# -*- coding: utf-8 -*-
"""
UiPath 단계별 테스트용 입력(fixtures)과 Python 정답(expected)을 만든다.

  python make_fixtures.py

생성 위치 (UiPath 프로젝트 폴더):
  prompts\\prompt_v1_1.txt                      프롬프트 템플릿 (프로젝트 안으로 복사)
  genai_test\\{세션}_transcript.txt             마스킹된 전사본 (Main_Step123 입력)
  test_data\\step1\\{case}\\prompt.txt, transcript.txt      Step1 입력
  test_data\\step2\\{case}.txt                  Step2 입력 (모델 응답 원문)
  test_data\\step3\\{scenario}\\attempt1..3.txt Step3 입력 (시도별 응답)
  test_data\\expected\\...                       Python(analyze.py)이 계산한 정답
"""
import json
import os
import shutil

import common as C

PROMPT_SRC = os.path.join(C.ROOT, "prompts", "prompt_v1_1.txt")
GENAI_SRC = os.path.join(C.ROOT, "test", "out", "stt", "genai")
GENAI_DST = os.path.join(C.UIPATH, "genai_test")


def jdump(o, **kw):
    return json.dumps(o, ensure_ascii=False, **kw)


def base_response():
    """검증을 통과하는 기준 응답(실제 모델 응답에서 감정 필드 제거·화이트리스트 적용)"""
    raw = C.read_text(os.path.join(GENAI_DST, "S00007731_response.txt"))
    d = C.analyze.extract_json(raw)
    return {k: d[k] for k in C.analyze.REQUIRED}


def step2_cases():
    b = base_response()
    cases = {}

    def put(name, text):
        cases[name] = text

    # --- 실제 모델 응답 5건 (이전 프롬프트로 만든 것: sentiment 필드가 섞여 있어 화이트리스트도 함께 검증됨)
    for sid in C.SIDS:
        put("real_" + sid, C.read_text(os.path.join(GENAI_DST, "%s_response.txt" % sid)))
    # --- 통과해야 하는 경우
    put("valid_plain", jdump(b))
    put("valid_pretty", jdump(b, indent=2))
    put("valid_fenced", "```json\n" + jdump(b) + "\n```")
    put("valid_prefix_suffix", "분석 결과입니다.\n" + jdump(b) + "\n도움이 되었길 바랍니다.")
    put("valid_nulls", jdump({**b, "customer_company": None, "customer_question": None, "agent_action": None,
                              "follow_up": None, "keywords": [], "entities": []}))
    put("valid_stray_fields", jdump({**b, "sentiment": "NEGATIVE", "foo": {"bar": 1}}))
    put("valid_date_like_text", jdump({**b, "summary": "2026-11-24T15:30:00+09:00 에 접수된 건. 11월 21일까지 회신."}))
    put("valid_int_confidence_1", jdump({**b, "type_confidence": 1}))
    put("valid_int_confidence_0", jdump({**b, "type_confidence": 0}))
    put("valid_summary_300", jdump({**b, "summary": "가" * 300}))
    put("valid_entity_value_number", jdump({**b, "entities": [{"type": "AMOUNT", "value": 5}]}))
    # --- 실패해야 하는 경우 (오류 메시지까지 Python 과 같아야 함)
    no_type = {k: v for k, v in b.items() if k != "type"}
    put("missing_one", jdump(no_type))
    put("missing_many", jdump({"type": "INQUIRY"}))
    put("bad_type_text", jdump({**b, "type": "SPAM"}))
    put("bad_type_number", jdump({**b, "type": 5}))
    put("bad_type_null", jdump({**b, "type": None}))
    put("bad_type_quote", jdump({**b, "type": "it's"}))
    put("conf_over_1", jdump({**b, "type_confidence": 1.5}))
    put("conf_negative", jdump({**b, "type_confidence": -0.1}))
    put("conf_string", jdump({**b, "type_confidence": "0.9"}))
    put("conf_bool", jdump({**b, "type_confidence": True}))
    put("summary_empty", jdump({**b, "summary": ""}))
    put("summary_301", jdump({**b, "summary": "가" * 301}))
    put("summary_null", jdump({**b, "summary": None}))
    put("question_empty", jdump({**b, "customer_question": ""}))
    put("question_201", jdump({**b, "customer_question": "가" * 201}))
    put("action_number", jdump({**b, "agent_action": 7}))
    put("followup_string", jdump({**b, "follow_up_required": "true"}))
    put("followup_null", jdump({**b, "follow_up_required": None}))
    put("keywords_6", jdump({**b, "keywords": list("abcdef")}))
    put("keywords_not_array", jdump({**b, "keywords": "배송"}))
    put("entities_not_array", jdump({**b, "entities": {"type": "PRODUCT", "value": "x"}}))
    put("entities_bad_type", jdump({**b, "entities": [{"type": "PERSON", "value": "x"}]}))
    put("entities_empty_value", jdump({**b, "entities": [{"type": "ORG", "value": ""}]}))
    put("entities_item_not_object", jdump({**b, "entities": ["x"]}))
    put("multiple_errors", jdump({**b, "type": "SPAM", "type_confidence": 2, "summary": "", "keywords": list("abcdef")}))
    # --- JSON 자체가 깨진 경우
    put("two_objects", jdump(b) + " " + jdump(b))
    put("no_json", "죄송합니다. JSON을 만들 수 없습니다.")
    put("broken_json", jdump(b)[:-15] + "}")
    put("empty_text", "")
    put("braces_reversed", "} 거꾸로 {")
    return cases


def step3_scenarios():
    b = base_response()
    V = jdump(b)
    BADTYPE = jdump({**b, "type": "SPAM"})
    KW6 = jdump({**b, "keywords": list("abcdef")})
    MISSING = jdump({k: v for k, v in b.items() if k not in ("customer_company", "summary")})
    NOJSON = "죄송하지만 JSON을 만들 수 없습니다."
    BROKEN = jdump(b)[:-15] + "}"
    return {
        "sc1_first_ok": [V, V, V],
        "sc2_second_ok": [NOJSON, V, V],
        "sc3_third_ok": [BADTYPE, BROKEN, V],
        "sc4_all_fail_validation": [BADTYPE, KW6, MISSING],
        "sc5_all_fail_parse": [NOJSON, BROKEN, NOJSON],
        "sc6_fenced_first_ok": ["```json\n" + V + "\n```", NOJSON, NOJSON],
        "sc7_last_reason_wins": [NOJSON, BADTYPE, KW6],
    }



def raw_stt(sid):
    return json.load(open(os.path.join(C.ROOT, "test", "out", "stt", "%s_raw.json" % sid), encoding="utf-8-sig"))


def make_transcript(texts, speaker_conf="HIGH", unknown=False):
    """parse_clova.to_transcript 와 같은 모양의 전사 객체를 만든다 (상담원·고객 번갈아)"""
    segs = []
    for i, t in enumerate(texts):
        sp = "UNKNOWN" if unknown else ("AGENT" if i % 2 == 0 else "CUSTOMER")
        segs.append({"speaker": sp, "start_sec": round(i * 3.0 + 0.4, 2), "end_sec": round(i * 3.0 + 2.5, 2), "text": t})
    full = "\n".join("[%s] %s" % (C.parse_clova.ROLE_LABEL[s["speaker"]], s["text"]) for s in segs)
    return {"full_text": full, "segments": segs, "speaker_confidence": speaker_conf}


def step4_cases():
    cases = {}
    for sid in C.SIDS:
        cases["real_" + sid] = C.parse_clova.to_transcript(raw_stt(sid))
    cases["pii_phone"] = make_transcript(["제 번호는 010-1234-5678이에요", "01012345678 / 010.1234.5678 / 02-123-4567", "010 1234 5678로 연락 주세요"])
    cases["pii_rrn_card_account"] = make_transcript(["주민번호 900101-1234567 입니다", "900101 – 2345678", "카드 1234-5678-9012-3456 그리고 1234 5678 9012 3456",
                                                     "계좌는 110-123-456789-01입니다"])
    cases["pii_email"] = make_transcript(["hello.world+tag@example.co.kr 으로 보내 주세요", "메일은 a@b.com 입니다"])
    cases["pii_address"] = make_transcript(["네 서울특별시 종로구 종로 1가 111다시1입니다.", "경기도 수원시 팔달구 매산로 12 입니다",
                                            "서울 마포구 아싸동 암흑길 30 빌딩 305호입니다."])
    cases["pii_password_birth"] = make_transcript(["비밀번호는 imkin g123 느낌표 느낌표로 해주세요", "비밀 번호가 abc1234예요", "01년생이고 1990년생도 있어요", "제가 99년생이에요"])
    cases["pii_names"] = make_transcript(["안녕하세요 상담원 김하늘입니다", "성함은 홍길동입니다", "저는 박서준이에요", "저는 고객입니다", "이름은 최민수님이라고 합니다"])
    cases["no_pii_false_positives"] = make_transcript(["오늘로 3일째입니다", "2026-11-24에 접수", "5분 정도 분량", "고객센터입니다", "상담원 연결해 주세요",
                                                       "서울 지점에 방문했어요", "서울에서 3일째입니다", "부산 사는데 1학년이에요", "비밀번호는 잊어버렸어요", "90년대생이에요"])
    cases["mixed_overlap"] = make_transcript(["주민번호 900101-2345678 전화 010-9999-8888 카드 1111-2222-3333-4444 입니다", "계좌 123-456-7890123 / 2026-11-24 / 010-1234-5678"])
    cases["unknown_speaker_low"] = make_transcript(["상담원 이영희입니다 전화는 010-5555-6666", "비밀번호는 abc123 입니다"], speaker_conf="LOW", unknown=True)
    return cases


def step5_scenarios():
    """이름 -> dict(raw, attempts, seq, now, ...). 응답은 이번 Main_Step123 실행의 실제 모델 응답을 쓴다."""
    resp = {sid: C.read_text(os.path.join(GENAI_DST, "%s_response.txt" % sid)) for sid in C.SIDS}
    b = base_response()
    NOJSON = "죄송하지만 JSON을 만들 수 없습니다."
    BADTYPE = jdump({**b, "type": "SPAM"})
    sc = {}
    for i, sid in enumerate(C.SIDS, 1):
        sc["ok_" + sid] = dict(raw=raw_stt(sid), attempts=[resp[sid]])
    sc["conf_boundary_0_6"] = dict(raw=raw_stt("S00007731"), attempts=[jdump({**b, "type_confidence": 0.6})])
    sc["conf_below_0_59"] = dict(raw=raw_stt("S00007731"), attempts=[jdump({**b, "type_confidence": 0.59})])
    sc["retry_then_ok"] = dict(raw=raw_stt("S00007728"), attempts=[NOJSON, resp["S00007728"]])
    sc["analysis_failed"] = dict(raw=raw_stt("S00007730"), attempts=[BADTYPE, BADTYPE, BADTYPE])
    failed = json.load(open(os.path.join(C.ROOT, "test", "dummy_clova_response_failed.json"), encoding="utf-8-sig"))
    sc["stt_failed"] = dict(raw=failed, attempts=[NOJSON])
    sc["input_failed"] = dict(raw=failed, attempts=[NOJSON], forced_stt_error={"stage": "INPUT", "reason": "음성 파일이 없음"})
    for i, (name, d) in enumerate(sc.items(), 1):
        d.update(file_name=name + ".wav", seq=i, now="2026-11-24T17:%02d:05+09:00" % i, prompt_version="v1_1", genai_model="mock-rule-based")
        if d.get("forced_stt_error"):
            d["stt_stage"], d["stt_error"], d["tr"] = d["forced_stt_error"]["stage"], d["forced_stt_error"]["reason"], None
            continue
        try:
            tr = C.parse_clova.to_transcript(d["raw"])
            d["stt_stage"], d["stt_error"] = "", ""
            d["tr"] = tr
        except Exception as e:  # noqa: BLE001
            d["stt_stage"], d["stt_error"] = "STT", str(e)
            d["tr"] = None
    return sc


def main():
    if hasattr(__import__("sys").stdout, "reconfigure"):
        __import__("sys").stdout.reconfigure(encoding="utf-8")
    # 프롬프트 템플릿과 전사본을 UiPath 프로젝트 안으로
    os.makedirs(os.path.join(C.UIPATH, "prompts"), exist_ok=True)
    shutil.copyfile(PROMPT_SRC, os.path.join(C.UIPATH, "prompts", "prompt_v1_1.txt"))
    for sid in C.SIDS:
        shutil.copyfile(os.path.join(GENAI_SRC, "%s_transcript.txt" % sid), os.path.join(GENAI_DST, "%s_transcript.txt" % sid))
    # 이전 실행의 fixtures 는 지우고 다시 만든다 (정답과 어긋나지 않게)
    if os.path.isdir(C.TEST):
        shutil.rmtree(C.TEST)

    # ---- Step1
    n1 = 0
    cases1 = {sid: (C.read_text(PROMPT_SRC), C.read_text(os.path.join(GENAI_SRC, "%s_transcript.txt" % sid))) for sid in C.SIDS}
    cases1["BADPROMPT"] = ("# 설명만 있고 블록이 없는 프롬프트\n그냥 텍스트\n", cases1["S00007727"][1])
    for case, (prompt, tr) in cases1.items():
        d = os.path.join(C.TEST, "step1", case)
        C.write_text(os.path.join(d, "prompt.txt"), prompt)
        C.write_text(os.path.join(d, "transcript.txt"), tr)
        s, u, e = C.expected_step1(os.path.join(d, "prompt.txt"), tr)
        ed = os.path.join(C.TEST, "expected", "step1", case)
        C.write_text(os.path.join(ed, "system.txt"), s)
        C.write_text(os.path.join(ed, "user.txt"), u)
        C.write_text(os.path.join(ed, "error.txt"), e)
        n1 += 1
    # ---- Step2
    cases2 = step2_cases()
    for name, text in cases2.items():
        C.write_text(os.path.join(C.TEST, "step2", name + ".txt"), text)
        C.write_text(os.path.join(C.TEST, "expected", "step2", name + ".json"), jdump(C.expected_step2(text)))
    # ---- Step3
    sc3 = step3_scenarios()
    for name, atts in sc3.items():
        for i, t in enumerate(atts, 1):
            C.write_text(os.path.join(C.TEST, "step3", name, "attempt%d.txt" % i), t)
        C.write_text(os.path.join(C.TEST, "expected", "step3", name + ".json"), jdump(C.expected_step3(atts)))

    # ---- Step4: 마스킹 (입력: 마스킹 전 전사 JSON, 정답: mask_pii.mask_transcript)
    cases4 = step4_cases()
    for name, tr in cases4.items():
        C.write_text(os.path.join(C.TEST, "step4", name + ".json"), jdump(tr))
        C.write_text(os.path.join(C.TEST, "expected", "step4", name + ".json"), jdump(C.expected_step4(tr)))
    # Main_Step1to5 입력: 세션별 마스킹 전 전사 JSON
    for sid in C.SIDS:
        C.write_text(os.path.join(GENAI_DST, "%s_transcript.json" % sid), jdump(C.parse_clova.to_transcript(raw_stt(sid))))
    # ---- Step5: 최종 JSON 조립 (입력: 마스킹 결과 + 분석 결과 + 메타, 정답: run_dummy.process 를 시각만 고정해 실행)
    sc5 = step5_scenarios()
    for name, d in sc5.items():
        base = os.path.join(C.TEST, "step5", name)
        if d["tr"] is not None:
            C.write_text(os.path.join(base, "masked.json"), jdump(C.expected_step4(d["tr"])))
            C.write_text(os.path.join(base, "analysis.json"), jdump(C.expected_step3(d["attempts"])))
        else:
            C.write_text(os.path.join(base, "masked.json"), "{}")
            C.write_text(os.path.join(base, "analysis.json"), "{}")
        meta = {"fileName": d["file_name"], "seq": d["seq"], "nowIso": d["now"], "promptVersion": d["prompt_version"],
                "sttEngine": "clova-speech", "genaiModel": d["genai_model"], "sttStage": d["stt_stage"], "sttError": d["stt_error"]}
        C.write_text(os.path.join(base, "meta.json"), jdump(meta))
        doc = C.expected_step5(d["raw"], d["file_name"], d["seq"], d["attempts"], d["now"], d["prompt_version"], d["genai_model"],
                               stt_error=({"stage": d["stt_stage"], "reason": d["stt_error"]} if d["stt_error"] and d["tr"] is None and d.get("forced_stt_error") else None))
        C.write_text(os.path.join(C.TEST, "expected", "step5", name + ".json"), jdump(doc))
    stat = {}
    for name in sc5:
        s = json.load(open(os.path.join(C.TEST, "expected", "step5", name + ".json"), encoding="utf-8"))["status"]
        stat[s] = stat.get(s, 0) + 1

    # Main_Step1to7(저장된 STT 응답 모드) 입력
    for sid in C.SIDS:
        shutil.copyfile(os.path.join(C.ROOT, "test", "out", "stt", "%s_raw.json" % sid), os.path.join(GENAI_DST, "%s_stt_raw.json" % sid))
    # ---- Step6·7: STT 호출(가짜 서버로 정답 생성)과 STT 응답 파싱
    import fixtures_stt
    names6 = fixtures_stt.build_step6()
    names7 = fixtures_stt.build_step7()

    # ---- Step8: 폴더 순회·파일 이동 (Python 기준 구현 run_folder.py 의 결과가 정답)
    import fixtures_folder
    fixtures_folder.build_step8()
    names8b = fixtures_folder.build_step8b()

    # 케이스 목록(XAML 생성기가 사용)
    C.write_text(os.path.join(C.TEST, "cases.json"), jdump({"step1": list(cases1), "step2": list(cases2), "step3": list(sc3), "step4": list(cases4), "step5": list(sc5), "step6": names6, "step7": names7, "step8b": names8b}, indent=1))
    print("Step1 %d건, Step2 %d건, Step3 %d건, Step4 %d건, Step5 %d건 생성 → %s" % (n1, len(cases2), len(sc3), len(cases4), len(sc5), C.TEST))
    print("  Step5 정답 status 분포:", stat)
    print("Step6 %d건, Step7 %d건, Step8b %d건 생성" % (len(names6), len(names7), len(names8b)))
    ok = sum(1 for n in cases2 if C.expected_step2(cases2[n])["isValid"])
    print("  Step2 정답 분포: 통과 %d / 실패 %d" % (ok, len(cases2) - ok))


if __name__ == "__main__":
    main()
