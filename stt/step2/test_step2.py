# -*- coding: utf-8 -*-
"""키·음성 없이 돌리는 Step2 자체 테스트:  python test_step2.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyze
import mask_pii
import run_dummy

T = os.path.join(os.path.dirname(HERE), "test")
passed = 0


def check(name, cond):
    global passed
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)
    passed += 1


# 1. 마스킹 단위
m = lambda s: mask_pii.mask_text(s)
check("전화 010-1234-5678", m("제 번호는 010-1234-5678이에요")[0] == "제 번호는 [PHONE]이에요")
check("전화 공백/점 구분 + 유선 02-123-4567", m("01012345678 / 010.1234.5678 / 02-123-4567")[0] == "[PHONE] / [PHONE] / [PHONE]")
check("주민번호", m("901231-1234567")[0] == "[RRN]")
check("카드번호", m("1234-5678-9012-3456")[0] == "[CARD]" and m("1234 5678 9012 3456")[0] == "[CARD]")
check("계좌번호(하이픈)", m("계좌는 110-123-456789입니다")[0] == "계좌는 [ACCOUNT]입니다")
check("이메일", m("hello@example.com 으로")[0] == "[EMAIL] 으로")
check("이름: 상담원 ○○○", m("상담원 김하늘입니다")[0] == "상담원 [NAME]입니다")
check("이름: 성함은 ○○○", m("성함은 홍길동입니다")[0] == "성함은 [NAME]입니다")
check("주소: 시·도+구+번지", m("네 서울특별시 종로구 종로 1가 111다시1입니다.")[0] == "네 [ADDRESS].")
check("주소: 건물·호수", m("서울 마포구 아싸동 암흑길 30 빌딩 305호입니다.")[0] == "[ADDRESS].")
check("주소: 경기도 수원시", m("경기도 수원시 팔달구 매산로 12 입니다")[0] == "[ADDRESS] 입니다")
check("비밀번호(영문·숫자·특수문자 읽기)", m("비밀번호는 imkin g123 느낌표 느낌표로 해주세요")[0] == "비밀번호는 [PASSWORD] 해주세요")
check("출생연도 NN년생·NNNN년생", m("01년생이고 1990년생도")[0] == "[BIRTH]이고 [BIRTH]도")
# 오탐 방지: 날짜·기간·건수·일반 문장은 그대로
for s in ("오늘로 3일째입니다", "2026-11-24에 접수", "5분 정도 분량", "고객센터입니다", "상담원 연결해 주세요",
          "서울 지점에 방문했어요", "서울에서 3일째입니다", "부산 사는데 1학년이에요", "비밀번호는 잊어버렸어요", "90년대생이에요"):
    check("오탐 없음: " + s, m(s)[0] == s)
# 겹침: 주민번호가 전화/계좌로 잘못 잡히지 않음
check("주민번호가 [RRN] 하나로만 치환", m("주민번호 900101-2345678 입니다") == ("주민번호 [RRN] 입니다", {**m("")[1], "rrn": 1}))

# 2. 더미 응답 2건: 마스킹 + 분류 + 스키마
docs = []
for i, pii, kind, typ in ((1, "hello@example.com", "email", "INQUIRY"), (2, "010-1234-5678", "phone", "COMPLAINT")):
    resp = json.load(open(os.path.join(T, "sample_response_%d.json" % i), encoding="utf-8"))
    d = run_dummy.process(resp, "sample_response_%d.json" % i, i)
    docs.append(d)
    raw = json.dumps(d, ensure_ascii=False)
    check("샘플%d: 원본 PII가 결과 JSON 어디에도 없음" % i, pii not in raw)
    check("샘플%d: 마스킹 건수 %s=1, name=1" % (i, kind), d["pii"]["counts"][kind] == 1 and d["pii"]["counts"]["name"] == 1)
    check("샘플%d: 토큰이 전문에 존재" % i, "[%s]" % kind.upper() in d["transcript"]["full_text"])
    check("샘플%d: 유형=%s, status=SUCCESS" % (i, typ), d["type"] == typ and d["status"] == "SUCCESS")
    check("샘플%d: type_label 매핑" % i, d["type_label"] == analyze.TYPES[typ])
    errs = run_dummy.validate_schema(d)
    check("샘플%d: call_schema.json 통과" % i, errs is not None and not errs)

# 3. 프롬프트 조립
sys_p, user_p = analyze.build_prompt("[상담원] 안녕하세요\n[고객] 네")
check("프롬프트: {{TRANSCRIPT}} 치환·설명줄 제거", "{{TRANSCRIPT}}" not in user_p and "[고객] 네" in user_p and "# prompt_v1" not in sys_p)

# 4. 응답 전처리·재시도·실패 처리
good = analyze.mock_llm(sys_p, user_p.replace("[고객] 네", "[고객] 세금계산서 언제 발행되는지 궁금해서 전화드렸어요. 어떻게 받나요?"))
check("전처리: 코드펜스+설명 제거", analyze.extract_json("설명\n```json\n" + good + "\n```\n끝")["type"] in analyze.TYPES)
calls = {"n": 0}
def flaky(s, u):
    calls["n"] += 1
    return "죄송합니다, JSON을 만들 수 없습니다" if calls["n"] == 1 else good
r, e, retry = analyze.analyze("[상담원] 안녕하세요\n[고객] 네", llm=flaky)
check("재시도: 1회 실패 후 성공(retry_count=1)", r is not None and e is None and retry == 1)
bad = json.loads(good); bad["type"] = "SPAM"
r, e, retry = analyze.analyze("x", llm=lambda s, u: json.dumps(bad))
check("검증 실패 3회 → VALIDATION 오류, retry=2", r is None and e["stage"] == "VALIDATION" and retry == 2 and "type enum" in e["reason"])
fd = run_dummy.process(json.load(open(os.path.join(T, "dummy_clova_response_failed.json"), encoding="utf-8")), "failed.json", 9)
check("STT 실패 응답 → status=FAILED, 스키마 통과", fd["status"] == "FAILED" and fd["error"]["stage"] == "STT" and not run_dummy.validate_schema(fd))
lowc = run_dummy.process(json.load(open(os.path.join(T, "sample_response_1.json"), encoding="utf-8")), "x", 1,
                         llm=lambda s, u: json.dumps({**json.loads(good), "type_confidence": 0.4}))
check("확신도 0.4 → NEEDS_REVIEW", lowc["status"] == "NEEDS_REVIEW")

# 6. 감정 분석(sentiment) 제거 확인
check("REQUIRED에 sentiment 없음", "sentiment" not in analyze.REQUIRED and not hasattr(analyze, "SENTIMENTS"))
for pf in ("prompt_v1.txt", "prompt_v1_1.txt", "prompt_v1_2.txt"):
    body = "\n".join(l for l in open(os.path.join(os.path.dirname(HERE), "prompts", pf), encoding="utf-8").read().splitlines() if not l.lstrip().startswith("#"))
    check("%s: 감정 규칙·출력 필드·예시 값 없음" % pf, not any(w in body for w in ("sentiment", "POSITIVE", "NEGATIVE", "NEUTRAL", "고객의 전반적 감정")))
sch = open(os.path.join(os.path.dirname(HERE), "schema", "call_schema.json"), encoding="utf-8").read()
check("call_schema.json: sentiment 속성·필수 항목 없음", '"sentiment"' not in sch)
for d in docs:
    check("결과 JSON에 sentiment 키 없음", "sentiment" not in d)
stray = json.loads(good); stray["sentiment"] = "NEGATIVE"
r, e, retry = analyze.analyze("x", llm=lambda s, u: json.dumps(stray))
check("모델이 sentiment를 덧붙여도 결과에서 제거(재시도 없이 통과)", e is None and retry == 0 and "sentiment" not in r and set(r) == set(analyze.REQUIRED))
check("sentiment가 없는 응답이 정상 통과", analyze.analyze("x", llm=lambda s, u: json.dumps({k: v for k, v in json.loads(good).items() if k != "sentiment"}))[1] is None)

# 7. 유형 규칙은 행위 기준, 요약은 감정·태도 서술 금지
import re as _re2
for pf in ("prompt_v1.txt", "prompt_v1_1.txt", "prompt_v1_2.txt"):
    lines = [l for l in open(os.path.join(os.path.dirname(HERE), "prompts", pf), encoding="utf-8").read().splitlines() if not l.lstrip().startswith("#")]
    body = "\n".join(lines)
    check("%s: 유형 규칙에 감정·어조 기준 없음('불쾌감'·'불만 감정')" % pf, "불쾌" not in body and "불만 감정" not in body)
    check("%s: COMPLAINT는 문제 제기 + 해결·보상 요구 기준, 어조만으로 판단 금지" % pf, "해결·시정·보상·환불을 요구" in body and ("감정 표현만으로는 COMPLAINT로 판단하지 마세요" in body or "단순 요청만으로는 COMPLAINT로 판단하지 마세요" in body))
    check("%s: 요약 등에 감정·태도 서술 금지 규칙 있음" % pf, "감정·태도 서술 금지" in body and "summary, customer_question, agent_action, follow_up" in body)
    ex = [l for l in lines if l.startswith('{"type"')]
    check("%s: 예시 5개의 출력에 감정·태도 서술 없음" % pf, len(ex) == 5 and not any(_re2.search(r"불만을|불편을|호소|화를 냈|화가 났|만족|짜증|강하게", l) for l in ex))
    check("%s: 예시 2(COMPLAINT)는 요구 사실로 서술" % pf, any('"type":"COMPLAINT"' in l and "보상 여부를 요구했다" in l for l in ex))

# 8. 입출력 폴더를 config.json 의 paths 에서 읽기 (run_folder.resolve_folders)
import tempfile as _tf
import run_folder as _rf
_d = _tf.mkdtemp(prefix="tp8_")
_base = os.path.join(_d, "proj")
_cfg = os.path.join(_d, "config.json")


def _folders(obj):
    if obj is None:
        if os.path.exists(_cfg):
            os.remove(_cfg)
    else:
        open(_cfg, "w", encoding="utf-8").write(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False))
    return _rf.resolve_folders(_cfg, _base)


_dflt = {"inDir": os.path.join(_base, "calls", "in"), "outDir": os.path.join(_base, "calls", "out"),
         "doneDir": os.path.join(_base, "calls", "done"), "failedDir": os.path.join(_base, "calls", "failed")}
check("폴더 설정: 설정 파일이 없으면 calls\\in|out|done|failed", _folders(None) == _dflt)
check("폴더 설정: paths 가 없으면 기본값", _folders({"clova_invoke_url": "x"}) == _dflt)
check("폴더 설정: 깨진 JSON이어도 기본값(예외 없음)", _folders("{not json") == _dflt)
_abs = os.path.join(_d, "robot", "in")
_r = _folders({"paths": {"input_dir": _abs, "output_dir": "res", "done_dir": "<자리표시자>", "failed_dir": ""}})
check("폴더 설정: 절대 경로는 그대로", _r["inDir"] == os.path.normpath(_abs))
check("폴더 설정: 상대 경로는 프로젝트 폴더 기준", _r["outDir"] == os.path.join(_base, "res"))
check("폴더 설정: 자리표시자·빈 값은 기본값", _r["doneDir"] == _dflt["doneDir"] and _r["failedDir"] == _dflt["failedDir"])
check("폴더 설정: config.example.json 의 자리표시자는 모두 기본값",
      _rf.resolve_folders(os.path.join(os.path.dirname(HERE), "config.example.json"), _base) == _dflt)
import shutil as _sh
_sh.rmtree(_d, ignore_errors=True)

print("\n통과: %d" % passed)
