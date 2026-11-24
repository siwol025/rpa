# -*- coding: utf-8 -*-
"""
③ 결과 JSON 이 ④ RPA 코어(uipath/)가 받아들이는 계약을 지키는지 검사한다.

④ 의 검증 규칙(uipath/CallCenter/Pipeline.cs ProcessFile·ValidateRequired)을 그대로 따라 하되,
기준값은 ④ 의 Config.xlsx(Constants·ColumnMap·ErrorColumnMap)에서 읽는다. 값을 이 파일에 복사해 두지 않는다.

  1) schema_version 이 Constants.ResultSchemaVersion 과 같아야 한다 (다르면 업무 오류 → error 폴더)
  2) call_id 가 비어 있지 않아야 한다
  3) status 가 StatusSuccess / StatusNeedsReview / StatusFailed 중 하나여야 한다
  4) FAILED 이면 error.stage, error.reason 이 있어야 한다
  5) 그 외(SUCCESS/NEEDS_REVIEW)이면 ColumnMap 에서 WriteByRobot=Y 이고 RequiredWhen 이 Y 로 시작하는 경로가 모두 있어야 한다

사용법
  python check_rpa_contract.py --config <repo>\\uipath\\Data\\Config.xlsx  결과.json  또는  폴더
종료 코드: 0 = 모두 통과, 1 = 위반 있음
"""
import argparse
import glob
import json
import os
import sys

import openpyxl


def load_contract(config_path):
    wb = openpyxl.load_workbook(config_path, data_only=True)
    consts = {r[0]: ("" if r[1] is None else str(r[1])) for r in wb["Constants"].iter_rows(min_row=2, values_only=True) if r[0]}
    rows = list(wb["ColumnMap"].iter_rows(min_row=2, values_only=True))
    required = []
    for r in rows:
        order, col, path, dtype, write, req = r[0], r[1], r[2], r[3], r[4], r[5]
        if str(write).strip().upper() == "Y" and str(req or "").strip().upper().startswith("Y"):
            required.append({"column": col, "path": path, "always": "전체" in str(req)})
    return consts, required


def get(doc, path):
    """④ 의 ResultJson.Get 과 같은 규칙: 점 경로, 없거나 null 이면 None, 불린은 true/false 문자열"""
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    if cur is None:
        return None
    if isinstance(cur, bool):
        return "true" if cur else "false"
    return cur if isinstance(cur, str) else json.dumps(cur, ensure_ascii=False)


def check_doc(doc, consts, required):
    """위반 사유 목록(비어 있으면 ④ 가 정상 처리)"""
    probs = []
    exp = consts.get("ResultSchemaVersion", "")
    sv = get(doc, "schema_version")
    if exp and sv != exp:
        return ["스키마 버전 불일치: %s (기대 %s)" % (sv or "(없음)", exp)]
    if not (get(doc, "call_id") or "").strip():
        return ["필수값 누락: call_id"]
    status = get(doc, "status")
    if status not in (consts.get("StatusSuccess"), consts.get("StatusNeedsReview"), consts.get("StatusFailed")):
        return ["알 수 없는 status: %s" % (status or "(없음)")]
    if status == consts.get("StatusFailed"):
        if not (get(doc, "error.stage") or "").strip() or not (get(doc, "error.reason") or "").strip():
            probs.append("FAILED 건에 error.stage/error.reason 없음")
        return probs
    for r in required:
        if not (get(doc, r["path"]) or "").strip():
            probs.append("필수값 누락: %s (%s)" % (r["path"], r["column"]))
    return probs


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="④ 의 Config.xlsx 경로 (uipath\\Data\\Config.xlsx)")
    ap.add_argument("paths", nargs="+", help="결과 JSON 파일 또는 폴더")
    a = ap.parse_args()
    consts, required = load_contract(a.config)
    files = []
    for p in a.paths:
        files += sorted(glob.glob(os.path.join(p, "*.json"))) if os.path.isdir(p) else [p]
    bad = 0
    print("기준: ResultSchemaVersion=%s, 필수 경로=%s" % (consts.get("ResultSchemaVersion"), [r["path"] for r in required]))
    for f in files:
        doc = json.load(open(f, encoding="utf-8-sig"))
        probs = check_doc(doc, consts, required)
        print("%s %s %s" % ("PASS" if not probs else "FAIL", os.path.basename(f), "(status=%s)" % doc.get("status") if not probs else "; ".join(probs)))
        bad += bool(probs)
    print("\n%d개 중 통과 %d, 위반 %d" % (len(files), len(files) - bad, bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
