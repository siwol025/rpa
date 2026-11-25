# -*- coding: utf-8 -*-
"""
GenAI 연결 테스트 (일정표 No.18): 실제 STT 전사본 → 마스킹 → 프롬프트 → OpenAI 호출 → 응답 검증

건당 1회만 호출하고(재시도 없음) 응답 원문을 저장해, 프롬프트 자체가 JSON 형식을 잘 지키는지 본다.
결과 파일: test\\out\\stt\\genai\\{세션}_system.txt / _user.txt / _transcript.txt / _response.txt  (저장소 제외 폴더)

사용법
  python run_genai_test.py --sid S00007727          # 1건
  python run_genai_test.py --all                    # 5건 전부
  python run_genai_test.py --sid S00007727 --dry-run   # 프롬프트만 만들고 호출하지 않음
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "step1"))
import analyze  # noqa: E402
import check_genai_response  # noqa: E402
import mask_pii  # noqa: E402
import openai_llm  # noqa: E402
import parse_clova  # noqa: E402

SESSIONS = ["S00007727", "S00007728", "S00007729", "S00007730", "S00007731"]
STT_DIR = os.path.join(ROOT, "test", "out", "stt")
OUT_DIR = os.path.join(STT_DIR, "genai")


def build(sid, prompt_path):
    resp = json.load(open(os.path.join(STT_DIR, "%s_raw.json" % sid), encoding="utf-8-sig"))
    tr = parse_clova.to_transcript(resp)
    masked, pii = mask_pii.mask_transcript(tr)
    system, user = analyze.build_prompt(masked["full_text"], prompt_path)
    return system, user, masked, pii


def save(sid, kind, text):
    with open(os.path.join(OUT_DIR, "%s_%s.txt" % (sid, kind)), "w", encoding="utf-8") as f:
        f.write(text)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sid", action="append", help="세션 ID (여러 번 지정 가능)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--prompt", default=os.path.join(ROOT, "prompts", "prompt_v1_2.txt"))
    ap.add_argument("--config", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-output-tokens", type=int, default=None,
                    help="config.json의 max_output_tokens 대신 사용 (추론 모델은 추론 토큰도 포함되므로 크게)")
    a = ap.parse_args()
    sids = SESSIONS if a.all else (a.sid or [])
    if not sids:
        ap.error("--sid 또는 --all 필요")
    os.makedirs(OUT_DIR, exist_ok=True)

    llm = None
    if not a.dry_run:
        try:
            cfg = openai_llm.load_openai_config(a.config or None)
            if a.max_output_tokens:
                cfg["max_output_tokens"] = a.max_output_tokens
            llm = openai_llm.make_llm(cfg)
        except openai_llm.LlmError as e:
            print("중단: %s" % e)
            sys.exit(2)

    rows = []
    for sid in sids:
        system, user, masked, pii = build(sid, a.prompt)
        save(sid, "system", system)
        save(sid, "user", user)
        save(sid, "transcript", masked["full_text"])
        info = "전사 %d자, 화자신뢰 %s, 마스킹 %s" % (len(masked["full_text"]), masked["speaker_confidence"],
                                                {k: v for k, v in pii["counts"].items() if v} or "없음")
        if a.dry_run:
            print("%s: 프롬프트 저장(호출 안 함) — %s" % (sid, info))
            continue
        try:
            text = llm(system, user)
        except openai_llm.LlmError as e:
            print("%s: 호출 실패 — %s" % (sid, e))
            rows.append((sid, "호출 실패", str(e)))
            if "HTTP 401" in str(e) or "키" in str(e):
                break  # 키 문제면 나머지도 실패하므로 중단
            continue
        save(sid, "response", text)
        d, problems, notes = check_genai_response.check(text, masked["full_text"])
        verdict = "통과" if d is not None and not problems else "검증 실패"
        print("\n=== %s (%s)" % (sid, info))
        if d is not None:
            print("type=%s 확신도=%s | %s" % (d.get("type"), d.get("type_confidence"), d.get("summary")))
        for n in notes:
            print("  참고: " + n)
        for p in problems:
            print("  문제: " + p)
        print("  → %s" % verdict)
        rows.append((sid, verdict, "type=%s conf=%s" % (d.get("type"), d.get("type_confidence")) if d else "; ".join(problems)))

    if rows:
        print("\n요약")
        for sid, v, extra in rows:
            print("  %s  %s  %s" % (sid, v, extra))
        sys.exit(0 if all(v == "통과" for _, v, _ in rows) else 1)


if __name__ == "__main__":
    main()
