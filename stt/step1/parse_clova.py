# -*- coding: utf-8 -*-
"""
CLOVA Speech 응답 → call_schema.json 의 transcript 객체로 변환 (Step2 화자 정제의 초안)

처리 순서
  1) segments[] 에서 text(없으면 textEdited), start/end(ms→초), speaker.label 추출
  2) 같은 화자의 연속 발화를 하나로 병합
  3) 화자 라벨 → AGENT/CUSTOMER 매핑
       - 최우선: 첫 발화에 인사 키워드(고객지원센터/상담원 등)가 있는 화자 = 상담원
       - 기본 규칙: 먼저 말한 화자 = 상담원
       - 보조 규칙: 상담원 인사/안내 문구가 더 많이 나온 화자 = 상담원 (점수 차이 2 이상이면 우선)
       - 두 규칙이 어긋나거나 판단 근거가 약하면 speaker_confidence = LOW
  4) '[상담원] … / [고객] …' 형식의 full_text 생성

사용법
  python parse_clova.py --in ..\\test\\dummy_clova_response.json --out ..\\test\\dummy_transcript.json
"""
import argparse
import json
import sys

# 첫 발화에 이 키워드가 있는 화자 = 상담원 (인사말 규칙, 가장 우선)
GREETING_KEYWORDS = ["고객지원센터", "고객센터", "상담원", "무엇을 도와"]
AGENT_PHRASES = [
    "고객지원센터", "고객센터입니다", "무엇을 도와", "도와드리", "도와 드리", "안내해 드리", "안내드리",
    "확인해 보겠", "확인해보겠", "죄송합니다", "보내 드리겠", "말씀해 주", "확인 후",
]
ROLE_LABEL = {"AGENT": "상담원", "CUSTOMER": "고객", "UNKNOWN": "알수없음"}


def _speaker_label(seg):
    sp = seg.get("speaker")
    if isinstance(sp, dict) and sp.get("label") not in (None, ""):
        return str(sp["label"])
    dz = seg.get("diarization")
    if isinstance(dz, dict) and dz.get("label") not in (None, ""):
        return str(dz["label"])
    return "?"


def extract_segments(resp):
    if resp.get("result") != "COMPLETED":
        raise ValueError("COMPLETED 상태가 아닌 응답: %s" % resp.get("result"))
    segs = []
    for s in resp.get("segments") or []:
        text = (s.get("textEdited") or s.get("text") or "").strip()
        if not text:
            continue
        segs.append({
            "label": _speaker_label(s),
            "start_sec": round(float(s.get("start", 0)) / 1000.0, 2),  # ms 가정
            "end_sec": round(float(s.get("end", 0)) / 1000.0, 2),
            "text": text,
        })
    if not segs:
        raise ValueError("발화가 없음")
    return segs


def merge_consecutive(segs):
    merged = []
    for s in segs:
        if merged and merged[-1]["label"] == s["label"]:
            merged[-1]["text"] += " " + s["text"]
            merged[-1]["end_sec"] = s["end_sec"]
        else:
            merged.append(dict(s))
    return merged


def assign_roles(segs):
    labels = []
    for s in segs:
        if s["label"] not in labels:
            labels.append(s["label"])
    score = {l: 0 for l in labels}
    for s in segs:
        score[s["label"]] += sum(s["text"].count(p) for p in AGENT_PHRASES)

    if len(labels) < 2:
        return {labels[0]: "UNKNOWN"}, "LOW"
    first, second = labels[0], labels[1]

    # 인사말 규칙: 각 화자의 첫 발화에 인사 키워드가 있는지 (한 화자에게만 있을 때 확정)
    first_utt = {}
    for s in segs:
        first_utt.setdefault(s["label"], s["text"])
    greeters = [l for l in labels if any(k in first_utt[l] for k in GREETING_KEYWORDS)]
    if len(greeters) == 1 and len(labels) == 2:
        agent = greeters[0]
        customer = second if agent == first else first
        return {agent: "AGENT", customer: "CUSTOMER"}, "HIGH"
    a, b = score[first], score[second]
    if abs(a - b) >= 2:
        agent = first if a > b else second
        conf = "HIGH" if agent == first else "LOW"
    else:
        agent = first
        conf = "HIGH" if a > b else "LOW"
    customer = second if agent == first else first
    roles = {agent: "AGENT", customer: "CUSTOMER"}
    for l in labels[2:]:
        roles[l] = "UNKNOWN"
        conf = "LOW"
    return roles, conf


def to_transcript(resp):
    merged = merge_consecutive(extract_segments(resp))
    roles, conf = assign_roles(merged)
    segments = [{
        "speaker": roles[s["label"]],
        "start_sec": s["start_sec"],
        "end_sec": s["end_sec"],
        "text": s["text"],
    } for s in merged]
    full = "\n".join("[%s] %s" % (ROLE_LABEL[x["speaker"]], x["text"]) for x in segments)
    return {"full_text": full, "segments": segments, "speaker_confidence": conf}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="CLOVA 원본 응답 JSON (또는 clova_stt.py 결과 wrapper)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    with open(a.inp, encoding="utf-8") as f:
        data = json.load(f)
    resp = data["stt_json"] if "stt_json" in data and data["stt_json"] else data
    tr = to_transcript(resp)
    text = json.dumps(tr, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
