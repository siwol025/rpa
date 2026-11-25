# -*- coding: utf-8 -*-
"""
UiPath 변환 검증 공통: 경로, Python 기준 결과(정답) 계산, 비교.

기준(정답)은 기존 Python 구현(step2/analyze.py)이 계산한다. UiPath/VB 쪽 결과가 이와 같은지 비교한다.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STEP2 = os.path.dirname(HERE)
ROOT = os.path.dirname(STEP2)
sys.path.insert(0, STEP2)
sys.path.insert(0, os.path.join(ROOT, "step1"))
import analyze  # noqa: E402
import mask_pii  # noqa: E402
import parse_clova  # noqa: E402
import run_dummy  # noqa: E402
import datetime as _dt  # noqa: E402

UIPATH = os.environ.get("UIPATH_PROJECT") or os.path.join(ROOT, "uipath")  # 기본: 저장소의 stt/uipath
TEST = os.path.join(UIPATH, "test_data")          # 입력 + 정답(expected)
SIDS = ["S00007727", "S00007728", "S00007729", "S00007730", "S00007731"]
MAX_RETRY = 2


def read_text(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return f.read().replace("\r\n", "\n")


def write_text(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


# ---------------------------------------------------------------- Python 기준 결과 (정답)
def expected_step1(prompt_path, transcript):
    """(system, user, error) — analyze.build_prompt 결과"""
    try:
        s, u = analyze.build_prompt(transcript, prompt_path)
        return s, u, ""
    except ValueError as e:
        return "", "", str(e)


def expected_step2(text):
    """{'isValid', 'errorText', 'cleaned'} — analyze.extract_json + validate + 화이트리스트"""
    try:
        d = analyze.extract_json(text)
    except Exception as e:  # noqa: BLE001
        return {"isValid": False, "errorText": "응답 파싱 실패(%s)" % type(e).__name__, "cleaned": None}
    errs = analyze.validate(d)
    if errs:
        return {"isValid": False, "errorText": "; ".join(errs), "cleaned": None}
    return {"isValid": True, "errorText": "", "cleaned": {k: d[k] for k in analyze.REQUIRED}}


def expected_step3(attempts, max_retry=MAX_RETRY):
    """{'result', 'error', 'retry_count'} — analyze.analyze 를 시도별 응답 목록으로 실행"""
    seq = list(attempts)
    state = {"i": 0}

    def llm(system, user):
        t = seq[min(state["i"], len(seq) - 1)]
        state["i"] += 1
        return t
    r, e, n = analyze.analyze("x", llm=llm, max_retry=max_retry)
    return {"result": r, "error": e, "retry_count": n}


def expected_step4(transcript_obj):
    """{'transcript', 'pii'} — mask_pii.mask_transcript"""
    masked, pii = mask_pii.mask_transcript(transcript_obj)
    return {"transcript": masked, "pii": pii}


def expected_step5(raw_resp, file_name, seq, attempts, now_iso, prompt_version, genai_model="mock-rule-based", stt_error=None):
    """최종 결과 문서 — run_dummy.process 를 시각만 고정해서 실행 (시각·번호는 입력으로 받는 구조와 같게)"""
    fixed = _dt.datetime.fromisoformat(now_iso)
    seq_l = list(attempts)
    state = {"i": 0}

    def llm(system, user):
        t = seq_l[min(state["i"], len(seq_l) - 1)]
        state["i"] += 1
        return t

    class _FixedDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    run_dummy.datetime = _FixedDT
    try:
        doc = run_dummy.process(raw_resp, file_name, seq, llm=llm, prompt_version=prompt_version, stt_error=stt_error)
    finally:
        run_dummy.datetime = _dt.datetime
    if genai_model != doc["processing"]["genai_model"]:
        doc["processing"]["genai_model"] = genai_model
    return doc


# ---------------------------------------------------------------- 비교
def _norm(s):
    return s.replace("\r\n", "\n")


def _first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


def compare_step1(actual_dir):
    """actual_dir/step1/<case>/{system,user,error}.txt  vs  test_data/expected/step1/<case>/..."""
    exp_root = os.path.join(TEST, "expected", "step1")
    rows = []
    for case in sorted(os.listdir(exp_root)):
        probs = []
        for name in ("system", "user", "error"):
            ep = os.path.join(exp_root, case, name + ".txt")
            ap = os.path.join(actual_dir, "step1", case, name + ".txt")
            if not os.path.exists(ap):
                probs.append("%s.txt 없음" % name)
                continue
            e, a = read_text(ep), read_text(ap)
            if e != a:
                i = _first_diff(e, a)
                probs.append("%s.txt 다름(길이 정답 %d / 실제 %d, 첫 차이 위치 %d)" % (name, len(e), len(a), i))
        rows.append((case, probs))
    return rows


def compare_step2(actual_dir):
    exp_root = os.path.join(TEST, "expected", "step2")
    rows = []
    for fn in sorted(os.listdir(exp_root)):
        case = fn[:-5]
        e = json.load(open(os.path.join(exp_root, fn), encoding="utf-8"))
        ap = os.path.join(actual_dir, "step2", fn)
        if not os.path.exists(ap):
            rows.append((case, ["결과 파일 없음"]))
            continue
        a = json.loads(read_text(ap))
        probs = []
        for k in ("isValid", "errorText", "cleaned"):
            if e[k] != a.get(k):
                probs.append("%s 다름: 정답=%s / 실제=%s" % (k, json.dumps(e[k], ensure_ascii=False)[:120], json.dumps(a.get(k), ensure_ascii=False)[:120]))
        rows.append((case, probs))
    return rows


def compare_step3(actual_dir):
    exp_root = os.path.join(TEST, "expected", "step3")
    rows = []
    for fn in sorted(os.listdir(exp_root)):
        case = fn[:-5]
        e = json.load(open(os.path.join(exp_root, fn), encoding="utf-8"))
        ap = os.path.join(actual_dir, "step3", fn)
        if not os.path.exists(ap):
            rows.append((case, ["결과 파일 없음"]))
            continue
        a = json.loads(read_text(ap))
        probs = []
        for k in ("result", "error", "retry_count"):
            if e[k] != a.get(k):
                probs.append("%s 다름: 정답=%s / 실제=%s" % (k, json.dumps(e[k], ensure_ascii=False)[:140], json.dumps(a.get(k), ensure_ascii=False)[:140]))
        rows.append((case, probs))
    return rows


def compare_main(genai_dir):
    """Main_Step123 실행 결과: genai_test/{sid}_analysis.json 과 ui_{sid}_system/user.txt 를
    Python 이 같은 입력으로 계산한 값과 비교한다. (응답은 실행 때마다 달라지므로 저장된 응답 {sid}_response.txt 를 기준으로 함)"""
    rows = []
    for sid in SIDS:
        probs = []
        resp_p = os.path.join(genai_dir, "%s_response.txt" % sid)
        ana_p = os.path.join(genai_dir, "%s_analysis.json" % sid)
        if not os.path.exists(ana_p) or not os.path.exists(resp_p):
            rows.append((sid, ["%s_analysis.json 또는 %s_response.txt 없음 (Main_Step123 미실행)" % (sid, sid)]))
            continue
        # (1) 프롬프트: UiPath 가 만든 것 vs Python 이 만든 것
        for name in ("system", "user"):
            up = os.path.join(genai_dir, "ui_%s_%s.txt" % (sid, name))
            pp = os.path.join(genai_dir, "%s_%s.txt" % (sid, name))
            if not os.path.exists(up):
                probs.append("ui_%s_%s.txt 없음" % (sid, name))
            elif read_text(up) != read_text(pp):
                probs.append("프롬프트 %s 다름 (첫 차이 위치 %d)" % (name, _first_diff(read_text(up), read_text(pp))))
        # (2) 응답 검증 결과: UiPath 의 최종 결과 vs Python 이 저장된 응답을 검증한 결과
        exp = expected_step2(read_text(resp_p))
        act = json.loads(read_text(ana_p))
        if act.get("error") is None:
            if not exp["isValid"]:
                probs.append("UiPath는 성공이라는데 Python은 저장된 응답을 실패로 판정: %s" % exp["errorText"])
            elif act["result"] != exp["cleaned"]:
                probs.append("검증된 결과(result)가 Python과 다름")
        else:
            if exp["isValid"]:
                probs.append("UiPath는 실패(%s)인데 Python은 마지막 응답을 통과로 판정" % act["error"].get("reason"))
        rows.append((sid, probs, act.get("retry_count")))
    return rows


def _load(p):
    return json.loads(read_text(p))


def compare_step4(actual_dir):
    exp_root = os.path.join(TEST, "expected", "step4")
    rows = []
    for fn in sorted(os.listdir(exp_root)):
        case = fn[:-5]
        e = _load(os.path.join(exp_root, fn))
        ap = os.path.join(actual_dir, "step4", fn)
        if not os.path.exists(ap):
            rows.append((case, ["결과 파일 없음"]))
            continue
        a = _load(ap)
        probs = []
        if e["pii"] != a.get("pii"):
            probs.append("pii 다름: 정답=%s / 실제=%s" % (json.dumps(e["pii"], ensure_ascii=False), json.dumps(a.get("pii"), ensure_ascii=False)))
        et, at = e["transcript"], a.get("transcript") or {}
        if et.get("full_text") != at.get("full_text"):
            i = _first_diff(et["full_text"], at.get("full_text") or "")
            probs.append("full_text 다름 (첫 차이 위치 %d): 정답=…%s… / 실제=…%s…" % (i, et["full_text"][max(0, i - 15):i + 25].replace("\n", " / "), (at.get("full_text") or "")[max(0, i - 15):i + 25].replace("\n", " / ")))
        if et.get("segments") != at.get("segments"):
            probs.append("segments 다름")
        if et.get("speaker_confidence") != at.get("speaker_confidence"):
            probs.append("speaker_confidence 다름")
        rows.append((case, probs))
    return rows


def _doc_diff(e, a, skip=()):
    probs = []
    for k in sorted(set(e) | set(a)):
        if k in skip:
            continue
        if k == "processing":
            for kk in sorted(set(e[k]) | set(a.get(k, {}))):
                if kk in skip:
                    continue
                if e[k].get(kk) != a.get(k, {}).get(kk):
                    probs.append("processing.%s 다름: 정답=%s / 실제=%s" % (kk, e[k].get(kk), a.get(k, {}).get(kk)))
        elif e.get(k) != a.get(k):
            probs.append("%s 다름: 정답=%s / 실제=%s" % (k, json.dumps(e.get(k), ensure_ascii=False)[:110], json.dumps(a.get(k), ensure_ascii=False)[:110]))
    return probs


def compare_step5(actual_dir):
    exp_root = os.path.join(TEST, "expected", "step5")
    rows = []
    for fn in sorted(os.listdir(exp_root)):
        case = fn[:-5]
        e = _load(os.path.join(exp_root, fn))
        ap = os.path.join(actual_dir, "step5", fn)
        if not os.path.exists(ap):
            rows.append((case, ["결과 파일 없음"]))
            continue
        a = _load(ap)
        probs = _doc_diff(e, a)
        sch = run_dummy.validate_schema(a)
        if sch:
            probs.append("call_schema.json 위반: %s" % sch)
        rows.append((case, probs, "status=%s" % a.get("status")))
    return rows


def compare_main5(genai_dir):
    """Main_Step1to5 결과 {sid}_result.json 을 Python 이 같은 입력(원본 STT 응답 + UiPath 가 저장한 모델 응답 + 같은 시각·번호)으로
    만든 문서와 비교한다. 재시도 횟수와 모델 이름은 실행마다 다를 수 있어 제외하고 따로 보여 준다."""
    rows = []
    for sid in SIDS:
        rp = os.path.join(genai_dir, "%s_result.json" % sid)
        resp_p = os.path.join(genai_dir, "%s_response.txt" % sid)
        if not os.path.exists(rp) or not os.path.exists(resp_p):
            rows.append((sid, ["%s_result.json 또는 %s_response.txt 없음 (Main_Step1to5 미실행)" % (sid, sid)]))
            continue
        a = _load(rp)
        raw = json.load(open(os.path.join(ROOT, "test", "out", "stt", "%s_raw.json" % sid), encoding="utf-8-sig"))
        e = expected_step5(raw, a["source"]["file_name"], int(a["call_id"][-3:]), [read_text(resp_p)], a["source"]["received_at"],
                           a["processing"]["prompt_version"], a["processing"]["genai_model"])
        probs = _doc_diff(e, a, skip=("retry_count",))
        sch = run_dummy.validate_schema(a)
        if sch:
            probs.append("call_schema.json 위반: %s" % sch)
        rows.append((sid, probs, "status=%s, 재시도 %s회" % (a.get("status"), a["processing"]["retry_count"])))
    return rows



def norm_requests(log):
    """가짜 서버가 받은 요청 기록을 비교하기 쉬운 모양으로 (파일 해시·params JSON·헤더 키 일치 여부)"""
    out = []
    for e in log:
        n = {"method": e["method"], "tail": e["tail"], "key_ok": e["key_ok"]}
        if e["method"] == "POST":
            parts = []
            for p in e.get("parts", []):
                q = {"name": p["name"], "filename": p["filename"]}
                if p["name"] == "media":
                    q["sha256"] = p["sha256"]
                    q["size"] = p["size"]
                else:
                    q["content_type"] = p["content_type"]
                    q["json"] = p.get("json")
                parts.append(q)
            n["parts"] = parts
        out.append(n)
    return out


def expected_step7(resp):
    """{'transcript', 'error'} — parse_clova.to_transcript"""
    try:
        return {"transcript": parse_clova.to_transcript(resp), "error": ""}
    except Exception as e:  # noqa: BLE001
        return {"transcript": None, "error": str(e)}


def _fetch_log(server_name, port=8765):
    import urllib.parse
    import urllib.request
    url = "http://127.0.0.1:%d/__log/%s" % (port, urllib.parse.quote(server_name))
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def compare_step6(actual_dir, fetch_log=None):
    """actual_dir/step6/<이름>.json 결과 + 가짜 서버가 받은 요청 기록을 Python 정답과 비교"""
    fetch = fetch_log or _fetch_log
    exp_root = os.path.join(TEST, "expected", "step6")
    rows = []
    for fn in sorted(os.listdir(exp_root)):
        case = fn[:-5]
        e = _load(os.path.join(exp_root, fn))
        ap = os.path.join(actual_dir, "step6", fn)
        if not os.path.exists(ap):
            rows.append((case, ["결과 파일 없음"]))
            continue
        a = _load(ap)
        probs = []
        for k in ("sttJson", "sttStage", "sttError"):
            if e["result"][k] != a.get(k):
                probs.append("%s 다름: 정답=%s / 실제=%s" % (k, json.dumps(e["result"][k], ensure_ascii=False)[:100], json.dumps(a.get(k), ensure_ascii=False)[:100]))
        try:
            got = norm_requests(fetch(e["server"]))
            if got != e["requests"]:
                probs.append("서버가 받은 요청이 다름: 정답=%s / 실제=%s" % (json.dumps(e["requests"], ensure_ascii=False)[:260], json.dumps(got, ensure_ascii=False)[:260]))
        except Exception as ex:  # noqa: BLE001
            probs.append("서버 요청 기록을 가져오지 못함(%s) — fake_clova.py 가 실행 중인지 확인" % type(ex).__name__)
        rows.append((case, probs))
    return rows


def compare_step7(actual_dir):
    exp_root = os.path.join(TEST, "expected", "step7")
    rows = []
    for fn in sorted(os.listdir(exp_root)):
        case = fn[:-5]
        e = _load(os.path.join(exp_root, fn))
        ap = os.path.join(actual_dir, "step7", fn)
        if not os.path.exists(ap):
            rows.append((case, ["결과 파일 없음"]))
            continue
        a = _load(ap)
        probs = []
        if e["error"] != a.get("error"):
            probs.append("error 다름: 정답=%s / 실제=%s" % (e["error"], a.get("error")))
        et, at = e["transcript"], a.get("transcript")
        if (et is None) != (at is None):
            probs.append("transcript 유무 다름")
        elif et is not None:
            if et["speaker_confidence"] != at.get("speaker_confidence"):
                probs.append("speaker_confidence 다름: 정답=%s / 실제=%s" % (et["speaker_confidence"], at.get("speaker_confidence")))
            if et["full_text"] != at.get("full_text"):
                i = _first_diff(et["full_text"], at.get("full_text") or "")
                probs.append("full_text 다름 (첫 차이 위치 %d)" % i)
            if et["segments"] != at.get("segments"):
                for i, (x, y) in enumerate(zip(et["segments"], at.get("segments") or [])):
                    if x != y:
                        probs.append("segments[%d] 다름: 정답=%s / 실제=%s" % (i, json.dumps(x, ensure_ascii=False)[:120], json.dumps(y, ensure_ascii=False)[:120]))
                        break
                else:
                    probs.append("segments 개수 다름: 정답 %d / 실제 %d" % (len(et["segments"]), len(at.get("segments") or [])))
        rows.append((case, probs))
    return rows



def list_tree(root, skip_top=()):
    """root 아래 모든 파일의 상대 경로(/ 구분)를 정렬해서"""
    out = []
    for d, _, fs in os.walk(root):
        rel_d = os.path.relpath(d, root).replace("\\", "/")
        for f in fs:
            rel = f if rel_d == "." else rel_d + "/" + f
            if rel.split("/")[0] in skip_top:
                continue
            out.append(rel)
    return sorted(out)


def norm_doc(d):
    """시각·모델 이름 같은 실행마다 달라지는 값을 뺀 비교용 문서"""
    import copy
    d = copy.deepcopy(d)
    d["call_id"] = "SEQ" + d["call_id"][-3:]
    d["source"].pop("received_at", None)
    d["processing"].pop("processed_at", None)
    d["processing"].pop("genai_model", None)
    return d


def compare_step8(run_root):
    """폴더 처리 결과(run_root: in/out/done/failed)를 Python 기준 구현 결과와 비교"""
    import re
    e = _load(os.path.join(TEST, "expected", "step8", "expected.json"))
    rows = []
    probs = []
    for k in ("in", "done", "failed"):
        got = list_tree(os.path.join(run_root, k))
        if got != e["folders"][k]:
            probs.append("%s 폴더의 파일이 다름: 정답=%s / 실제=%s" % (k, e["folders"][k], got))
    rows.append(("폴더별 파일 위치 (in/done/failed)", probs))

    out_dir = os.path.join(run_root, "out")
    out_files = list_tree(out_dir)
    probs = []
    if len(out_files) != e["out_count"]:
        probs.append("결과 JSON 개수 다름: 정답 %d / 실제 %d" % (e["out_count"], len(out_files)))
    docs = {}
    for fn in out_files:
        m = re.match(r"^(\d{8}_\d{6}_(\d{3}))\.json$", fn)
        if not m:
            probs.append("결과 파일 이름 형식이 다름: %s" % fn)
            continue
        d = _load(os.path.join(out_dir, fn))
        if d.get("call_id") != m.group(1):
            probs.append("%s 안의 call_id(%s)가 파일 이름과 다름" % (fn, d.get("call_id")))
        sch = run_dummy.validate_schema(d)
        if sch:
            probs.append("%s: call_schema.json 위반: %s" % (fn, sch))
        docs[d["source"]["file_name"]] = d
    rows.append(("결과 JSON 파일 (이름 형식·call_id·스키마)", probs))

    for name in sorted(e["docs"]):
        probs = []
        a = docs.get(name)
        if a is None:
            rows.append((name, ["결과 JSON 없음"]))
            continue
        probs = _doc_diff(e["docs"][name], norm_doc(a))
        rows.append((name, probs, "status=%s" % a["status"]))
    extra = sorted(set(docs) - set(e["docs"]))
    if extra:
        rows.append(("정답에 없는 결과", ["예상 밖의 결과 JSON: %s" % extra]))
    return rows


def compare_step8b(actual_dir):
    exp_root = os.path.join(TEST, "expected", "step8b")
    rows = []
    for fn in sorted(os.listdir(exp_root)):
        case = fn[:-5]
        e = _load(os.path.join(exp_root, fn))
        ap = os.path.join(actual_dir, "step8b", fn)
        if not os.path.exists(ap):
            rows.append((case, ["결과 파일 없음"]))
            continue
        a = _load(ap)
        probs = ["%s 다름: 정답=%s / 실제=%s" % (k, json.dumps(e[k], ensure_ascii=False), json.dumps(a.get(k), ensure_ascii=False)) for k in e if e[k] != a.get(k)]
        rows.append((case, probs))
    return rows


def compare_step8d(actual_dir):
    """입출력 폴더를 config.json 의 paths 에서 읽는 코드 조각 검증"""
    exp_root = os.path.join(TEST, "expected", "step8d")
    rows = []
    for fn in sorted(os.listdir(exp_root)):
        case = fn[:-5]
        e = _load(os.path.join(exp_root, fn))
        ap = os.path.join(actual_dir, "step8d", fn)
        if not os.path.exists(ap):
            rows.append((case, ["결과 파일 없음"]))
            continue
        a = _load(ap)
        rows.append((case, ["%s 다름: 정답=%s / 실제=%s" % (k, e[k], a.get(k)) for k in e if e[k] != a.get(k)]))
    return rows


def compare_step8c(actual_dir):
    """결과 문서(Step5 정답 11건)에서 docStatus/errStage/errReason/retryCount 를 읽는 코드 조각 검증"""
    exp_root = os.path.join(TEST, "expected", "step5")
    rows = []
    for fn in sorted(os.listdir(exp_root)):
        case = fn[:-5]
        d = _load(os.path.join(exp_root, fn))
        err = d.get("error") or {}
        e = {"docStatus": d["status"], "errStage": err.get("stage", ""), "errReason": err.get("reason", ""), "retryCount": d["processing"]["retry_count"]}
        ap = os.path.join(actual_dir, "step5s", fn)
        if not os.path.exists(ap):
            rows.append((case, ["결과 파일 없음"]))
            continue
        a = _load(ap)
        rows.append((case, ["%s 다름: 정답=%s / 실제=%s" % (k, e[k], a.get(k)) for k in e if e[k] != a.get(k)]))
    return rows


def report(title, rows):
    print("\n== %s" % title)
    bad = 0
    for r in rows:
        case, probs = r[0], r[1]
        extra = ""
        if len(r) > 2 and r[2] is not None:
            extra = "  (%s)" % (r[2] if isinstance(r[2], str) else "재시도 %s회 사용" % r[2])
        if probs:
            bad += 1
            print("  FAIL %s%s" % (case, extra))
            for p in probs:
                print("       - " + p)
        else:
            print("  PASS %s%s" % (case, extra))
    print("  → %d건 중 일치 %d, 불일치 %d" % (len(rows), len(rows) - bad, bad))
    return bad
