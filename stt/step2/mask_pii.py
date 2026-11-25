# -*- coding: utf-8 -*-
"""
Step2-A: 개인정보(PII) 정규식 마스킹 (일정표 21·22번 초안)

적용 순서(중요): 화자 분리(Step1 parse_clova) → 마스킹(여기) → GenAI.
토큰: [RRN] 주민번호 / [CARD] 카드 / [PHONE] 전화 / [ACCOUNT] 계좌 / [EMAIL] 이메일 / [NAME] 이름
      [ADDRESS] 주소 / [PASSWORD] 비밀번호 / [BIRTH] 출생연도(예: 01년생)
  - 순서가 중요: 긴/구체적인 패턴(주민번호·카드)을 먼저 치환해야 전화·계좌 패턴과 겹치지 않는다.
  - prompt_v1.txt는 [PHONE], [NAME], [REF]만 예로 들고 있다. [RRN] 등은 '같은 마스킹 토큰' 규칙으로 처리되지만,
    v1.1에서 토큰 목록을 시스템 프롬프트에 명시하는 것을 권장.

한계(알려진 것)
  - [ID]는 '아이디는 ...' 뒤 영문·숫자 어절만 잡는다. 말로 읽은 이메일은 '골뱅이 … 점 …' 형태만 잡는다.
  - 숫자를 한글로 읽어 적은 경우("공일공 일이삼사")는 못 잡는다. STT가 숫자를 아라비아 숫자로 주는지 실제 응답으로 확인 필요.
  - 이름은 '상담원 ○○○입니다', '성함은 ○○○' 같은 문맥 패턴만 잡는다(이름 비식별 보강은 후순위 작업).
  - 계좌번호는 형식이 은행마다 달라 '하이픈으로 구분된 10~14자리' 정도만 잡는다.
  - 주소는 '시·도 + 시/군/구 + (최대 5어절) + 숫자가 든 어절'까지만 잡는다. 시·도 없이 말한 주소("마포구 ○○동")는 못 잡는다.
  - 비밀번호는 '비밀번호는' 바로 뒤의 영문·숫자·특수문자 읽기("느낌표" 등) 어절만 잡는다. 한글 단어 비밀번호는 못 잡는다.
  - 출생연도는 'NN년생'/'NNNN년생' 형식만 잡는다('90년대생'은 제외).

사용법
  python mask_pii.py --text "제 번호는 010-1234-5678이에요"
"""
import argparse
import re
import sys

# (종류, 토큰, 정규식) - 위에서 아래로 순서대로 적용
_PROV = (r"(?:서울특별시|서울시|서울|부산광역시|부산|대구광역시|대구|인천광역시|인천|광주광역시|광주|대전광역시|대전|"
         r"울산광역시|울산|세종특별자치시|세종|경기도|경기|강원특별자치도|강원도|강원|충청북도|충북|충청남도|충남|"
         r"전북특별자치도|전라북도|전북|전라남도|전남|경상북도|경북|경상남도|경남|제주특별자치도|제주도|제주)")
_PWTOK = r"(?:[A-Za-z0-9]+|느낌표|골뱅이|별표|샵|언더바|물결|대시|하이픈)[가-힣]{0,2}"
RULES = [
    # 말로 읽은 이메일: "dabin prince 123 골뱅이 네이버 점 컴" (주소 규칙보다 먼저)
    ("email", "[EMAIL]", re.compile(
        r"[A-Za-z0-9]+(?:\s+[A-Za-z0-9]+){0,3}\s*골뱅이\s*[가-힣A-Za-z0-9]+(?:\s*점\s*(?:컴|닷컴|넷|케이알|씨오|com|net|kr|co)){1,2}")),
    # 시·도 없이 말한 아파트·빌라 주소: "연희동 현대 21차 아파트"
    ("address", "[ADDRESS]", re.compile(
        r"[가-힣]{1,6}[동읍면리]\s+[가-힣0-9]+(?:\s*\d+\s*(?:차|단지|동|호))*\s*(?:아파트|빌라|오피스텔|APT)")),
    ("address", "[ADDRESS]", re.compile(
        _PROV + r"\s*[가-힣]{1,6}[시군구]\s+(?:[가-힣0-9\-]+\s+){0,5}[가-힣0-9\-]*\d[가-힣0-9\-]*")),
    ("rrn", "[RRN]", re.compile(r"(?<!\d)\d{6}\s*[-–]\s*[1-4]\d{6}(?!\d)")),
    ("card", "[CARD]", re.compile(r"(?<!\d)\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}(?!\d)")),
    ("phone", "[PHONE]", re.compile(r"(?<!\d)(?:01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}|0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4})(?!\d)")),
    ("email", "[EMAIL]", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("account", "[ACCOUNT]", re.compile(r"(?<!\d)\d{2,6}-\d{2,6}-\d{4,8}(?:-\d{1,3})?(?!\d)")),
    ("birth", "[BIRTH]", re.compile(r"(?<!\d)(?:19|20)?\d{2}년생")),
]
# 비밀번호: 앞 문맥('비밀번호는')은 남기고 값 어절들만 치환
PASSWORD_RULE = re.compile(r"(비밀\s?번호(?:는|가|를|도)?\s*)(" + _PWTOK + r"(?:\s+" + _PWTOK + r")*)")
# 카드번호를 말로 불러 준 경우: "카드번호는 02345-5648632 다시 132546974이고요" (그룹 1 문맥은 유지)
CARD_SPOKEN_RULE = re.compile(r"(카드\s?번호(?:는|가|를|도)?\s*)((?:\d[\d\-]*(?:\s*다시\s*)?)+)")
# 비밀번호 앞·뒷자리: "비밀번호 앞자리는 00이에요"
PASSWORD_PART_RULE = re.compile(r"(비밀\s?번호\s*(?:앞|뒷|뒤)\s?자리(?:는|가|를|도)?\s*)(\d{1,6})")
# 아이디: "아이디는 dabin jang으로" (영문·숫자 어절만)
ID_RULE = re.compile(r"(아이디(?:는|가|를|도)?\s*)([A-Za-z0-9]+(?:\s+[A-Za-z0-9]+){0,2})(?=[가-힣\s,.]|$)")
# 이름: 그룹 1(앞 문맥)은 남기고 그룹 2(이름)만 치환
NAME_RULES = [
    re.compile(r"(상담원\s*)([가-힣]{2,4})(?=\s*(?:입니다|이에요|예요|이라고))"),
    re.compile(r"((?:제\s*이름은|성함은|이름은|저는)\s*)([가-힣]{2,4})(?=\s*(?:입니다|이에요|예요|이라고|씨|님|인데))"),
    re.compile(r"((?:아이\s*|자녀\s*|아들\s*|딸\s*)?이름은\s*)([가-힣]{2,4})(?=\s*(?:이고|이며|이구요|이에요|예요|입니다))"),
    # 통화 끝 인사: "감사합니다. 강은빈이었습니다."
    re.compile(r"((?:^|[.?!]\s+))([가-힣]{3})(?=이었습니다)"),
]
NAME_STOPWORDS = {"고객", "상담원", "담당자", "회원", "관리자", "그것", "이것", "문제", "원인", "결과", "내용"}
EMPTY_COUNTS = {"phone": 0, "rrn": 0, "card": 0, "account": 0, "email": 0, "name": 0,
                "address": 0, "password": 0, "birth": 0, "id": 0}


def mask_text(text):
    """문자열 하나를 마스킹. (마스킹된 문자열, 종류별 건수 dict) 반환"""
    counts = dict(EMPTY_COUNTS)
    for kind, token, rx in RULES:
        text, n = rx.subn(token, text)
        counts[kind] += n
    text, n = CARD_SPOKEN_RULE.subn(lambda m: m.group(1) + "[CARD]", text)
    counts["card"] += n
    text, n = PASSWORD_PART_RULE.subn(lambda m: m.group(1) + "[PASSWORD]", text)
    counts["password"] += n
    text, n = PASSWORD_RULE.subn(lambda m: m.group(1) + "[PASSWORD]", text)
    counts["password"] += n
    text, n = ID_RULE.subn(lambda m: m.group(1) + "[ID]", text)
    counts["id"] += n
    for rx in NAME_RULES:
        def _sub(m):
            if m.group(2) in NAME_STOPWORDS:
                return m.group(0)
            counts["name"] += 1
            return m.group(1) + "[NAME]"
        text = rx.sub(_sub, text)
    return text, counts


def mask_transcript(tr):
    """parse_clova.to_transcript() 결과를 마스킹. 원본은 건드리지 않고 새 dict 반환.
    반환: (masked_transcript, pii) — pii는 call_schema.json의 pii 객체 형식"""
    total = dict(EMPTY_COUNTS)
    segs = []
    for s in tr["segments"]:
        t, c = mask_text(s["text"])
        for k, v in c.items():
            total[k] += v
        segs.append({**s, "text": t})
    role = {"AGENT": "상담원", "CUSTOMER": "고객", "UNKNOWN": "알수없음"}
    full = "\n".join("[%s] %s" % (role[s["speaker"]], s["text"]) for s in segs)
    masked = {"full_text": full, "segments": segs, "speaker_confidence": tr["speaker_confidence"]}
    return masked, {"masked": True, "counts": total}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    a = ap.parse_args()
    out, counts = mask_text(a.text)
    print(out)
    print(counts)


if __name__ == "__main__":
    main()
