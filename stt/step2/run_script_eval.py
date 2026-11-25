# -*- coding: utf-8 -*-
"""
대본 기반 유형 정확도 평가: test\\녹음_대본_5건.md 의 대사(정답 유형이 정해진 가상 대본)를
마스킹 → 프롬프트 → 모델 호출 → 응답 검증해 정답과 비교한다. (STT를 거치지 않으므로 STT 오류·화자 분리 영향은 빠진다)

사용법
  python run_script_eval.py --prompt ../prompts/prompt_v1_1.txt --tag v1_1
  python run_script_eval.py --prompt ../prompts/prompt_v1_2.txt --tag v1_2
결과: test\\out\\script_eval\\{tag}\\call_0N_{response,transcript}.txt 와 {tag}\\summary.json
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import analyze  # noqa: E402
import check_genai_response  # noqa: E402
import mask_pii  # noqa: E402
import openai_llm  # noqa: E402

SCRIPT_MD = os.path.join(ROOT, "test", "녹음_대본_5건.md")
OUT_ROOT = os.path.join(ROOT, "test", "out", "script_eval")


def load_scripts(path=SCRIPT_MD):
    """{'call_01': {'file': ..., 'expected': 'INQUIRY', 'lines': [('상담원'|'고객', 문장), ...]}}"""
    text = open(path, encoding="utf-8").read()
    out = {}
    for sec in re.split(r"(?m)^## ", text)[1:]:
        m = re.match(r"((?:call|edge)_\d+)_[^\s]*\.m4a\s*—\s*정답:\s*([A-Z]+)", sec)
        if not m:
            continue
        lines = [(r, t.strip()) for r, t in re.findall(r"(?m)^\*\*(상담원|고객):\*\*\s*(.+)$", sec)]
        out[m.group(1)] = {"file": sec.split("\n", 1)[0].split(" ")[0], "expected": m.group(2), "lines": lines}
    return out


def mask_lines(lines):
    masked = []
    for role, t in lines:
        mt, _ = mask_pii.mask_text(t)
        masked.append("[%s] %s" % (role, mt))
    return "\n".join(masked)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--script", default=SCRIPT_MD, help="대본 md 경로 (기본: 녹음_대본_5건.md)")
    ap.add_argument("--config", default="")
    ap.add_argument("--max-output-tokens", type=int, default=6000)
    a = ap.parse_args()
    cfg = openai_llm.load_openai_config(a.config or None)
    cfg["max_output_tokens"] = a.max_output_tokens
    llm = openai_llm.make_llm(cfg)
    scripts = load_scripts(a.script)
    out_dir = os.path.join(OUT_ROOT, a.tag)
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for cid, s in scripts.items():
        full = mask_lines(s["lines"])
        system, user = analyze.build_prompt(full, a.prompt)
        open(os.path.join(out_dir, cid + "_transcript.txt"), "w", encoding="utf-8").write(full)
        try:
            text = llm(system, user)
        except openai_llm.LlmError as e:
            print("%s: 호출 실패 — %s" % (cid, e))
            rows.append({"call": cid, "expected": s["expected"], "error": str(e)})
            continue
        open(os.path.join(out_dir, cid + "_response.txt"), "w", encoding="utf-8").write(text)
        d, problems, _ = check_genai_response.check(text, full)
        pred = d.get("type") if d else None
        conf = d.get("type_confidence") if d else None
        rows.append({"call": cid, "expected": s["expected"], "pred": pred, "conf": conf, "valid": bool(d) and not problems,
                     "problems": problems, "match": pred == s["expected"],
                     "customer_question": d.get("customer_question") if d else None, "summary": d.get("summary") if d else None,
                     "keywords": d.get("keywords") if d else None})
        print("%s 정답=%s 예측=%s 확신도=%s %s %s" % (cid, s["expected"], pred, conf, "일치" if pred == s["expected"] else "불일치",
                                                   "" if d and not problems else "검증문제:" + "; ".join(problems)))
    ok = [r for r in rows if r.get("match")]
    print("\n[%s] 유형 정확도: %d/%d, 검증 통과 %d/%d" % (a.tag, len(ok), len(rows), sum(1 for r in rows if r.get("valid")), len(rows)))
    json.dump({"prompt": os.path.basename(a.prompt), "model": cfg["model"], "rows": rows},
              open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
