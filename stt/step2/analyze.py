# -*- coding: utf-8 -*-
"""
Step2-B/Step3 대응: 프롬프트 조립 → LLM 호출(교체 가능) → 응답 전처리·JSON 파싱·필수 필드 검증 → 재시도

  build_prompt(masked_full_text, prompt_path) -> (system, user)   # prompt_v1.txt의 [SYSTEM]/[USER TEMPLATE] 사용
  mock_llm(system, user)  -> str      # 키 없이 돌리는 규칙 기반 가짜 LLM (아래 주의 참고)
  analyze(full_text, llm=mock_llm)    -> (result_dict | None, error | None, retry_count)

주의: mock_llm은 '진짜 LLM이 아니다'. 키워드 규칙으로 JSON을 흉내 낼 뿐이라
      (1) 프롬프트 조립 (2) 응답 전처리/파싱/검증/재시도 (3) 스키마 조립 같은 '배관'을 검증하는 용도다.
      분류 정확도는 실제 LLM으로만 평가할 수 있다. 실제 호출은 llm 인자에 (system, user)->str 함수를 넣으면 된다
      (UiPath에서는 Step3_Analyze.xaml이 같은 역할).
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT_PATH = os.path.join(ROOT, "prompts", "prompt_v1.txt")

TYPES = {"INQUIRY": "질의", "COMPLAINT": "불만", "SUGGESTION": "건의", "TRAINING": "교육 내용", "OTHER": "기타 문의"}
ENTITY_TYPES = {"PRODUCT", "ORG", "DATE", "AMOUNT", "REF_NO", "OTHER"}
REQUIRED = ["type", "type_confidence", "customer_company", "customer_question", "agent_action", "summary",
            "follow_up_required", "follow_up", "keywords", "entities"]


# ---------- 프롬프트 ----------
def build_prompt(full_text, prompt_path=PROMPT_PATH):
    raw = open(prompt_path, encoding="utf-8").read()
    lines = [l for l in raw.splitlines() if not l.lstrip().startswith("#")]  # 설명용 '#' 줄 제외
    body = "\n".join(lines)
    m = re.search(r"\[SYSTEM\](.*?)\[USER TEMPLATE\](.*)", body, flags=re.S)
    if not m:
        raise ValueError("prompt 파일에 [SYSTEM]/[USER TEMPLATE] 블록이 없음")
    return m.group(1).strip(), m.group(2).strip().replace("{{TRANSCRIPT}}", full_text)


# ---------- 가짜 LLM (규칙 기반) ----------
_COMPLAINT = ["말이 됩니까", "신뢰가 안", "항의", "불만", "화가", "짜증", "환불", "보상", "지장", "답답", "벌써 두 번째", "세 번째"]
_SUGGEST = ["좋겠어요", "있으면 좋", "추가해 주", "추가해 달라", "제안", "건의"]
_TRAIN = ["사용 방법", "사용법", "교육", "매뉴얼", "설명을 좀", "설명 좀"]
_INQUIRY = ["궁금", "언제", "어떻게", "문의", "?"]
_KEYWORDS = ["세금계산서", "발행", "이메일", "재발송", "마이페이지", "오류", "업로드", "개발팀", "알림 메일",
             "보고서", "교육 영상", "배송", "보상", "회신"]


def _hits(text, words):
    return sum(text.count(w) for w in words)


def mock_llm(system, user):
    """INPUT/OUTPUT 사이의 스크립트를 읽어 prompt_v1 출력 형식의 JSON 문자열을 만든다."""
    script = user.split("INPUT:", 1)[1].rsplit("OUTPUT:", 1)[0]
    cust = " ".join(re.findall(r"^\[고객\] (.+)$", script, flags=re.M))
    agent_lines = re.findall(r"^\[상담원\] (.+)$", script, flags=re.M)
    cust_lines = re.findall(r"^\[고객\] (.+)$", script, flags=re.M)

    if _hits(cust, _COMPLAINT) >= 2:
        t, conf = "COMPLAINT", 0.9
    elif _hits(cust, _SUGGEST) >= 1 and _hits(cust, _COMPLAINT) == 0:
        t, conf = "SUGGESTION", 0.85
    elif _hits(cust, _TRAIN) >= 1:
        t, conf = "TRAINING", 0.8
    elif _hits(cust, _INQUIRY) >= 1 and len(cust) > 40:
        t, conf = "INQUIRY", 0.85
    else:
        t, conf = "OTHER", 0.4

    q = cust_lines[0] if cust_lines else None
    action = next((l for l in agent_lines[1:] if re.search(r"안내|요청|약속|발송|전달|확인", l)), None)
    follow = bool(re.search(r"연락드리|회신|발송해 드리|전달하겠", " ".join(agent_lines)))
    kws = [k for k in _KEYWORDS if k in script][:5]
    ents = [{"type": "OTHER", "value": tok} for tok in re.findall(r"\[(?:PHONE|EMAIL|NAME)\]", script)[:0]]
    out = {
        "type": t, "type_confidence": conf, "customer_company": None,
        "customer_question": (q or "")[:200] or None,
        "agent_action": (action or "")[:200] or None,
        "summary": ("[모의 요약] 고객 발화 %d개, 상담원 발화 %d개. 주된 유형은 %s로 판단함." % (len(cust_lines), len(agent_lines), TYPES[t]))[:300],
        "follow_up_required": follow,
        "follow_up": ("상담원이 약속한 후속 연락/회신 필요" if follow else None),
        "keywords": kws, "entities": ents,
    }
    return json.dumps(out, ensure_ascii=False)


# ---------- 응답 전처리·검증 ----------
def extract_json(text):
    """코드펜스·앞뒤 설명을 걷어내고 첫 번째 JSON 객체를 파싱."""
    t = re.sub(r"```(?:json)?", "", text or "").strip()
    s, e = t.find("{"), t.rfind("}")
    if s < 0 or e <= s:
        raise ValueError("JSON 객체를 찾을 수 없음")
    return json.loads(t[s:e + 1])


def validate(d):
    """필수 필드·enum·길이 검사. 문제 목록 반환(비어 있으면 통과)."""
    errs = [k + " 누락" for k in REQUIRED if k not in d]
    if errs:
        return errs
    if d["type"] not in TYPES:
        errs.append("type enum 위반: %r" % d["type"])
    c = d["type_confidence"]
    if not isinstance(c, (int, float)) or isinstance(c, bool) or not 0 <= c <= 1:
        errs.append("type_confidence 범위 위반")
    if not isinstance(d["summary"], str) or not d["summary"] or len(d["summary"]) > 300:
        errs.append("summary 비었거나 300자 초과")
    for k in ("customer_question", "agent_action"):
        if d[k] is not None and (not isinstance(d[k], str) or not d[k] or len(d[k]) > 200):
            errs.append(k + " 길이/형식 위반")
    if not isinstance(d["follow_up_required"], bool):
        errs.append("follow_up_required는 boolean")
    if not isinstance(d["keywords"], list) or len(d["keywords"]) > 5:
        errs.append("keywords는 최대 5개 배열")
    if not isinstance(d["entities"], list) or any(
            not isinstance(x, dict) or x.get("type") not in ENTITY_TYPES or not x.get("value") for x in d["entities"]):
        errs.append("entities 형식 위반")
    return errs


def analyze(full_text, llm=mock_llm, max_retry=2, prompt_path=PROMPT_PATH):
    """반환: (결과 dict | None, error dict | None, retry_count). 실패 시 error는 call_schema의 error 형식."""
    system, user = build_prompt(full_text, prompt_path)
    last = "원인 불명"
    for attempt in range(max_retry + 1):
        try:
            d = extract_json(llm(system, user))
            errs = validate(d)
            if not errs:
                # 정의된 필드만 남긴다(감정 분석 등 추출 대상이 아닌 필드를 모델이 덧붙여도 결과에 싣지 않음)
                return {k: d[k] for k in REQUIRED}, None, attempt
            last = "; ".join(errs)
        except Exception as e:
            last = "응답 파싱 실패(%s)" % type(e).__name__
    return None, {"stage": "VALIDATION", "reason": "재시도 %d회 후에도 실패: %s" % (max_retry, last)}, max_retry
