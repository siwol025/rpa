# -*- coding: utf-8 -*-
"""
Step8(폴더 순회·파일 이동) 테스트 입력과 Python 정답을 만든다. make_fixtures.py 가 호출한다.

step8   : 입력 폴더 한 묶음(성공·검토 필요·분석 실패·STT 실패·입력 오류·이름 충돌·무시할 파일)을 만들고,
          Python 기준 구현(run_folder.py)을 가짜 CLOVA 서버에 실제로 돌려 정답(폴더별 파일 목록 + 결과 문서)을 만든다.
step8b  : 코드 조각(목록·이동) 단위의 파일 시스템 케이스. Python 정답은 run_folder 의 함수로 계산한다.
"""
import copy
import json
import os
import shutil
import tempfile

import common as C
import fake_clova
import fixtures_stt
import make_fixtures as MF
import run_folder  # step2

PORT = fixtures_stt.PORT


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


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


norm_doc = C.norm_doc


# ------------------------------------------------------------------ step8
def step8_inputs(base):
    """입력 한 묶음 (이름 -> 파일 내용)"""
    wav = fixtures_stt.wav_bytes()
    b = MF.base_response()
    valid = MF.jdump(b)
    lowconf = MF.jdump({**b, "type_confidence": 0.4})
    bad = MF.jdump({**b, "type": "SPAM"})
    files_in = {
        "high_01_success.wav": wav, "high_02_lowconf.wav": wav, "high_03_invalid_llm.wav": wav, "high_04_no_mock.wav": wav,
        "high_05_collision.wav": wav, "low_01_speaker_low.wav": wav, "clovafail_01.wav": wav, "http500_01.wav": wav, "nosegs_01.wav": wav,
        "empty_01.wav": b"", "notes_01.txt": b"not audio", "upper_01.MP3": wav,
        ".hidden.wav": wav, "~$tmp.wav": wav, "Thumbs.db": b"thumbs", "sub/high_99.wav": wav,
    }
    mock = {"high_01_success": valid, "high_02_lowconf": lowconf, "high_03_invalid_llm": bad, "high_05_collision": valid,
            "low_01_speaker_low": valid, "upper_01": valid}   # high_04_no_mock 는 일부러 없음
    for n, data in files_in.items():
        _write(os.path.join(base, "in", n), data)
    # 이미 같은 이름이 있는 상태 (이름 충돌 확인)
    _write(os.path.join(base, "done", "high_05_collision.wav"), b"old")
    _write(os.path.join(base, "failed", "clovafail_01.wav"), b"old")
    for stem, text in mock.items():
        _write(os.path.join(base, "mock_llm", stem + ".llm.txt"), text)
    cfg = {"clova_invoke_url": "http://127.0.0.1:%d/external/v1/by_name__folder" % PORT, "clova_secret_key": fake_clova.FAKE_KEY,
           "stt": {"poll_interval_sec": 0.01, "poll_max_count": 3}}
    _write(os.path.join(base, "config.json"), json.dumps(cfg, ensure_ascii=False))


def build_step8():
    src = os.path.join(C.TEST, "step8")
    step8_inputs(src)
    server_raw = os.path.join(C.TEST, "step6", "_server")
    shutil.copyfile(os.path.join(fixtures_stt.STT_RAW_DIR, "S00007727_raw.json"), os.path.join(server_raw, "raw_high.json"))
    work = tempfile.mkdtemp(prefix="step8_ref_")
    try:
        run = os.path.join(work, "run")
        shutil.copytree(src, run)
        srv, state = fake_clova.start_server(PORT, os.path.join(server_raw, "raw_ok.json"), os.path.join(server_raw, "raw_high.json"))
        try:
            def llm_for(stem):
                p = os.path.join(run, "mock_llm", stem + ".llm.txt")
                text = open(p, encoding="utf-8-sig").read() if os.path.exists(p) else ""
                return lambda s, u: text
            results = run_folder.run_folder(os.path.join(run, "in"), os.path.join(run, "out"), os.path.join(run, "done"),
                                            os.path.join(run, "failed"), os.path.join(run, "config.json"), llm_for)
        finally:
            srv.shutdown()
            srv.server_close()
        exp = {"folders": {k: list_tree(os.path.join(run, k)) for k in ("in", "done", "failed")},
               "out_count": len(list_tree(os.path.join(run, "out"))),
               "docs": {name: norm_doc(doc) for name, doc, _, _ in results}}
        C.write_text(os.path.join(C.TEST, "expected", "step8", "expected.json"), json.dumps(exp, ensure_ascii=False))
        return exp
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------ step8b (코드 조각 단위)
def step8b_cases():
    return {
        "list_basic": {"kind": "list", "entries": ["a.wav", "B.wav", "c.txt", "sub/x.wav", ".hidden.wav", "~$tmp.wav", "Thumbs.db", "THUMBS.DB", "desktop.ini",
                                                   "한글.wav", "z_last.mp3", "A_upper.wav"]},
        "list_empty": {"kind": "list", "entries": []},
        "list_only_skipped": {"kind": "list", "entries": [".a", "~$b", "Thumbs.db"]},
        "move_plain": {"kind": "move", "src": "a.wav", "dest_entries": []},
        "move_collision_1": {"kind": "move", "src": "a.wav", "dest_entries": ["a.wav"]},
        "move_collision_chain": {"kind": "move", "src": "a.wav", "dest_entries": ["a.wav", "a_1.wav", "a_2.wav"]},
        "move_collision_gap": {"kind": "move", "src": "a.wav", "dest_entries": ["a.wav", "a_2.wav"]},
        "move_no_ext": {"kind": "move", "src": "readme", "dest_entries": ["readme"]},
        "move_multi_dots": {"kind": "move", "src": "x.y.wav", "dest_entries": ["x.y.wav"]},
        "move_dest_is_dir": {"kind": "move", "src": "a.wav", "dest_entries": ["a.wav/"]},
        "move_dest_missing": {"kind": "move", "src": "a.wav", "dest_entries": None},
        "move_src_missing": {"kind": "move", "src": "gone.wav", "dest_entries": [], "src_exists": False},
        "move_korean_name": {"kind": "move", "src": "통화 녹음.wav", "dest_entries": ["통화 녹음.wav"]},
    }


def materialize(case, root):
    """case 의 파일 구조를 root 아래에 만든다. (list 용 in 폴더 / move 용 src 와 dest)"""
    if case["kind"] == "list":
        os.makedirs(os.path.join(root, "in"), exist_ok=True)
        for e in case["entries"]:
            _write(os.path.join(root, "in", e), b"x")
    else:
        os.makedirs(os.path.join(root, "src"), exist_ok=True)
        if case.get("src_exists", True):
            _write(os.path.join(root, "src", case["src"]), b"x")
        if case["dest_entries"] is not None:
            os.makedirs(os.path.join(root, "dest"), exist_ok=True)
            for e in case["dest_entries"]:
                if e.endswith("/"):
                    os.makedirs(os.path.join(root, "dest", e), exist_ok=True)
                else:
                    _write(os.path.join(root, "dest", e), b"old")


def expected_step8b(case):
    work = tempfile.mkdtemp(prefix="step8b_ref_")
    try:
        materialize(case, work)
        if case["kind"] == "list":
            return {"files": [os.path.basename(p) for p in run_folder.list_inputs(os.path.join(work, "in"))]}
        dest_dir = os.path.join(work, "dest")
        picked = os.path.basename(run_folder.unique_dest(dest_dir, case["src"]))
        moved, err = run_folder.move_unique(os.path.join(work, "src", case["src"]), dest_dir)
        return {"picked": picked, "moved": os.path.basename(moved) if moved else "", "error": err,
                "dest_listing": sorted(os.listdir(dest_dir)) if os.path.isdir(dest_dir) else [],
                "src_still_exists": os.path.exists(os.path.join(work, "src", case["src"]))}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build_step8b():
    cases = step8b_cases()
    for name, case in cases.items():
        C.write_text(os.path.join(C.TEST, "step8b", name + ".json"), json.dumps(case, ensure_ascii=False))
        C.write_text(os.path.join(C.TEST, "expected", "step8b", name + ".json"), json.dumps(expected_step8b(case), ensure_ascii=False))
    return list(cases)
