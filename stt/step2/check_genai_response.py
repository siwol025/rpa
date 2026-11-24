# -*- coding: utf-8 -*-
"""
GenAI 연결 테스트용 응답 검사 (일정표 No.18)

Studio의 Content Generation이 돌려준 텍스트를 파일로 저장한 뒤, 파이프라인이 쓰는 것과 같은 함수로 검사한다.
  1) 코드펜스·앞뒤 설명을 걷어내고 JSON 객체를 파싱 (analyze.extract_json)
  2) 필수 키·enum·길이 검증 (analyze.validate)
  3) 마스킹 토큰이 요약·키워드에 새어 나오지 않았는지 확인
  4) 이 응답으로 status가 무엇이 될지 미리 보기 (확신도 0.6 미만 → NEEDS_REVIEW)

사용법
  python check_genai_response.py --in ..\\test\\out\\stt\\genai\\S00007727_response.txt
  python check_genai_response.py --in resp.txt --transcript S00007727_transcript.txt   # 전사에 없는 내용이 지어졌는지 대략 확인
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyze  # noqa: E402

TOKEN_RE = re.compile(r"\[(?:PHONE|EMAIL|NAME|RRN|CARD|ACCOUNT|ADDRESS|PASSWORD|BIRTH)\]")
REVIEW_BELOW = 0.6  # run_dummy.py와 같은 기준 (STT 판정)


def check(text, transcript=None):
    """반환: (결과 dict | None, 문제 목록, 참고 목록)"""
    problems, notes = [], []
    try:
        d = analyze.extract_json(text)
    except Exception as e:  # noqa: BLE001
        return None, ["JSON 파싱 실패(%s): 응답에서 JSON 객체를 찾지 못함" % type(e).__name__], notes
    if re.search(r"```", text or ""):
        notes.append("응답에 코드펜스(```)가 붙어 있음 — 파이프라인이 제거하지만 프롬프트 지시는 지켜지지 않은 것")
    stripped = (text or "").strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        notes.append("JSON 앞뒤에 설명 문장이 붙어 있음 — 파이프라인이 제거하지만 프롬프트 지시는 지켜지지 않은 것")
    problems += analyze.validate(d)  # 감정 분석(sentiment)은 추출 대상이 아니므로 검증하지 않는다
    if isinstance(d, dict) and "sentiment" in d:
        notes.append("응답에 sentiment(감정) 필드가 있음 — 추출 대상이 아님. 제거되기 전 프롬프트로 만든 응답이므로 다시 생성 필요(검수에서는 무시)")
    if isinstance(d, dict):  # 다른 검증이 실패해도 토큰 노출은 함께 보고한다
        for k in ("summary", "customer_question", "agent_action", "follow_up"):
            v = d.get(k)
            if isinstance(v, str) and TOKEN_RE.search(v):
                problems.append("%s에 마스킹 토큰이 그대로 노출됨: %s" % (k, TOKEN_RE.findall(v)))
        for k in d.get("keywords") or []:
            if isinstance(k, str) and TOKEN_RE.search(k):
                problems.append("keywords에 마스킹 토큰이 들어감: %s" % k)
        for e in d.get("entities") or []:
            if isinstance(e, dict) and TOKEN_RE.search(str(e.get("value", ""))) and e.get("type") != "REF_NO":
                problems.append("entities에 마스킹 토큰이 들어감: %s" % e)
        if transcript:
            for e in (x for x in d.get("entities") or [] if isinstance(x, dict)):
                v = re.sub(r"\s", "", e.get("value", ""))
                if v and v not in re.sub(r"\s", "", transcript):
                    notes.append("entities 값이 전사에 그대로 나오지 않음(요약·정규화일 수 있음): %s" % e)
    return d, problems, notes


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="Content Generation 응답 텍스트 파일(UTF-8)")
    ap.add_argument("--transcript", default="", help="입력한 전사본 파일(선택)")
    a = ap.parse_args()
    text = open(a.inp, encoding="utf-8-sig").read()
    tr = open(a.transcript, encoding="utf-8-sig").read() if a.transcript else None
    d, problems, notes = check(text, tr)
    print("응답 길이: %d자" % len(text))
    if d is not None:
        conf = d.get("type_confidence")
        print("type=%s(%s) 확신도=%s follow_up=%s" % (
            d.get("type"), analyze.TYPES.get(d.get("type"), "?"), conf, d.get("follow_up_required")))
        print("customer_question: %s" % d.get("customer_question"))
        print("agent_action: %s" % d.get("agent_action"))
        print("summary: %s" % d.get("summary"))
        print("keywords: %s" % d.get("keywords"))
        print("entities: %s" % json.dumps(d.get("entities"), ensure_ascii=False))
        if isinstance(conf, (int, float)) and not problems:
            print("→ 이 응답이면 status = %s (확신도 %s, 기준 %s 미만이면 NEEDS_REVIEW; 화자 불확실이면 별도로 NEEDS_REVIEW)" % (
                "NEEDS_REVIEW" if conf < REVIEW_BELOW else "SUCCESS", conf, REVIEW_BELOW))
    for n in notes:
        print("참고: " + n)
    if problems:
        print("\n검증 실패 %d건:" % len(problems))
        for p in problems:
            print(" - " + p)
        sys.exit(1)
    print("\n검증 통과: 파이프라인이 그대로 받아들일 수 있는 응답입니다.")


if __name__ == "__main__":
    main()
