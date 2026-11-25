# -*- coding: utf-8 -*-
"""
입력 폴더의 음성 파일을 차례로 처리하는 Python 기준 구현 (UiPath 폴더 순회·파일 이동 변환의 비교 기준)

흐름 (README 의 처리 흐름과 같음)
  calls\\in 의 파일 → STT(clova_stt) → 파싱·마스킹·GenAI 분석·조립(run_dummy.process) → 결과 JSON 을 calls\\out 에 {call_id}.json 으로 저장
  → 원본 음성: 성공(SUCCESS/NEEDS_REVIEW)이면 calls\\done, 실패(FAILED)이면 calls\\failed 로 이동

규칙
  - 폴더 안의 파일만 처리하고 하위 폴더는 들어가지 않는다. 이름순(코드포인트 순)으로 처리하고 순번(seq)은 1부터.
  - 숨김·임시 파일(.으로 시작, ~$으로 시작, Thumbs.db, desktop.ini)은 건드리지 않고 그대로 둔다.
  - 지원하지 않는 형식·빈 파일은 FAILED(INPUT) 결과를 만들고 failed 로 옮긴다 (clova_stt 의 검사 결과 그대로).
  - 대상 폴더에 같은 이름이 있으면 덮어쓰지 않고 이름 뒤에 _1, _2 ... 를 붙인다 (확장자 앞).
  - 이동에 실패하면(잠김 등) 그 파일은 제자리에 두고 다음 파일로 간다.

사용법 (키·음성 없이 모의 LLM 으로)
  python run_folder.py --in ..\\calls\\in --out ..\\calls\\out --done ..\\calls\\done --failed ..\\calls\\failed
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "step1"))
import analyze  # noqa: E402
import clova_stt  # noqa: E402
import run_dummy  # noqa: E402

SKIP_PREFIXES = (".", "~$")
SKIP_NAMES = {"thumbs.db", "desktop.ini"}


def should_skip(name):
    return name.startswith(SKIP_PREFIXES) or name.lower() in SKIP_NAMES


def list_inputs(in_dir):
    """처리 대상 파일 경로 목록 (이름순)"""
    names = [n for n in os.listdir(in_dir) if os.path.isfile(os.path.join(in_dir, n)) and not should_skip(n)]
    return [os.path.join(in_dir, n) for n in sorted(names)]


def unique_dest(dest_dir, name):
    """dest_dir 에 name 이 이미 있으면 stem_1.ext, stem_2.ext ... 로"""
    p = os.path.join(dest_dir, name)
    if not os.path.exists(p):
        return p
    stem, ext = os.path.splitext(name)
    n = 1
    while os.path.exists(os.path.join(dest_dir, "%s_%d%s" % (stem, n, ext))):
        n += 1
    return os.path.join(dest_dir, "%s_%d%s" % (stem, n, ext))


def move_unique(src, dest_dir):
    """이동(이름 충돌 시 번호 부여). (새 경로, 오류 문자열) 반환"""
    try:
        os.makedirs(dest_dir, exist_ok=True)
        dest = unique_dest(dest_dir, os.path.basename(src))
        shutil.move(src, dest)
        return dest, ""
    except Exception as e:  # noqa: BLE001
        return "", "이동 실패(%s)" % type(e).__name__


def process_file(path, seq, config_path, llm, prompt_version):
    """파일 하나 → 최종 JSON 문서"""
    name = os.path.basename(path)
    out = clova_stt.transcribe(path, config_path)
    if out["error"]:
        return run_dummy.process(None, name, seq, llm=llm, prompt_version=prompt_version, stt_error=out["error"])
    return run_dummy.process(out["stt_json"], name, seq, llm=llm, prompt_version=prompt_version)


def run_folder(in_dir, out_dir, done_dir, failed_dir, config_path, llm_for, prompt_version="v1_2"):
    """llm_for(파일 이름 stem) → llm(system, user) 함수. 반환: [(원본 파일 이름, 문서, 결과 JSON 경로, 이동 후 경로)]"""
    for d in (in_dir, out_dir, done_dir, failed_dir):
        os.makedirs(d, exist_ok=True)
    results = []
    for seq, path in enumerate(list_inputs(in_dir), 1):
        name = os.path.basename(path)
        stem = os.path.splitext(name)[0]
        doc = process_file(path, seq, config_path, llm_for(stem), prompt_version)
        out_path = unique_dest(out_dir, doc["call_id"] + ".json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        moved, err = move_unique(path, failed_dir if doc["status"] == "FAILED" else done_dir)
        results.append((name, doc, out_path, moved or path))
    return results


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    root = os.path.dirname(HERE)
    ap.add_argument("--in", dest="in_dir", default=os.path.join(root, "calls", "in"))
    ap.add_argument("--out", default=os.path.join(root, "calls", "out"))
    ap.add_argument("--done", default=os.path.join(root, "calls", "done"))
    ap.add_argument("--failed", default=os.path.join(root, "calls", "failed"))
    ap.add_argument("--config", default=os.path.join(root, "config.json"))
    ap.add_argument("--mock-llm-dir", default="", help="{파일이름 stem}.llm.txt 를 모델 응답으로 사용 (없으면 빈 응답). 생략하면 규칙 기반 모의 LLM")
    a = ap.parse_args()

    def llm_for(stem):
        if not a.mock_llm_dir:
            return analyze.mock_llm
        p = os.path.join(a.mock_llm_dir, stem + ".llm.txt")
        text = open(p, encoding="utf-8-sig").read() if os.path.exists(p) else ""
        return lambda s, u: text

    for name, doc, out_path, moved in run_folder(a.in_dir, a.out, a.done, a.failed, a.config, llm_for):
        print("%s → %s (%s) → %s" % (name, os.path.basename(out_path), doc["status"], os.path.relpath(moved, os.path.dirname(a.in_dir))))


if __name__ == "__main__":
    main()
