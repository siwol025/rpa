# -*- coding: utf-8 -*-
"""
Step6(STT 호출)·Step7(STT 응답 파싱) 테스트 입력과 Python 정답을 만든다. make_fixtures.py 가 호출한다.

Step6: 가짜 CLOVA 서버(fake_clova.py)에 Python 의 clova_stt.transcribe 를 실제로 돌려 정답(결과 + 서버가 받은 요청 모양)을 만든다.
Step7: 정상 응답 5건(실제 STT 응답)과 화자 매핑·병합·반올림·오류 경로를 건드리는 가상 응답.
"""
import io
import json
import os
import shutil
import wave

import clova_stt  # step1 (common.py 가 경로를 잡아 둠)
import common as C
import fake_clova

PORT = 8765
STT_RAW_DIR = os.path.join(C.ROOT, "test", "out", "stt")


def wav_bytes(seconds=0.5, rate=8000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


# ------------------------------------------------------------------ Step6
def step6_specs():
    fast = {"poll_interval_sec": 0.01, "poll_max_count": 3}
    return {
        "ok_sync": dict(kind="ok_sync"),
        "ok_async": dict(kind="ok_async", stt={"poll_interval_sec": 0.01, "poll_max_count": 5}),
        "poll_timeout": dict(kind="poll_timeout", stt=fast),
        "poll_http_error": dict(kind="poll_http_error", stt=fast),
        "clova_failed": dict(kind="clova_failed"),
        "clova_failed_nomsg": dict(kind="clova_failed_nomsg"),
        "no_segments": dict(kind="no_segments"),
        "http_401": dict(kind="http_401"),
        "http_500": dict(kind="http_500"),
        "bad_json": dict(kind="bad_json"),
        "not_object": dict(kind="not_object"),
        "processing_no_token": dict(kind="processing_no_token"),
        "custom_params": dict(kind="custom_params", stt={"language": "en-US", "completion": "sync", "speaker_count_min": 1,
                                                         "speaker_count_max": 3, "noise_filtering": False}),
        "trailing_slash": dict(kind="ok_sync_trailing_slash", slash=True),
        "audio_upper_ext": dict(kind="ok_sync", audio="audio.MP3"),
        "audio_missing": dict(kind="ok_sync", audio=None),
        "audio_empty": dict(kind="ok_sync", audio="audio.wav", empty=True),
        "audio_badext": dict(kind="ok_sync", audio="audio.txt"),
        "config_missing": dict(kind="ok_sync", config=None),
        "config_badjson": dict(kind="ok_sync", config="{not json"),
        "config_not_object": dict(kind="ok_sync", config="[1, 2]"),
        "config_empty_key": dict(kind="ok_sync", override={"clova_secret_key": "여기에_Secret_Key"}),
        "config_empty_url": dict(kind="ok_sync", override={"clova_invoke_url": ""}),
    }


def build_step6():
    root = os.path.join(C.TEST, "step6")
    raw_ok = os.path.join(root, "_server", "raw_ok.json")
    os.makedirs(os.path.dirname(raw_ok), exist_ok=True)
    shutil.copyfile(os.path.join(STT_RAW_DIR, "S00007729_raw.json"), raw_ok)
    srv, state = fake_clova.start_server(PORT, raw_ok)
    names = []
    try:
        for name, sp in step6_specs().items():
            d = os.path.join(root, name)
            server_name = "%s__%s" % (sp["kind"], name)
            url = "http://127.0.0.1:%d/external/v1/%s" % (PORT, server_name) + ("/" if sp.get("slash") else "")
            cfg = {"clova_invoke_url": url, "clova_secret_key": fake_clova.FAKE_KEY}
            if sp.get("stt"):
                cfg["stt"] = sp["stt"]
            cfg.update(sp.get("override", {}))
            os.makedirs(d, exist_ok=True)
            if sp.get("config", "default") is not None:
                text = json.dumps(cfg, ensure_ascii=False) if sp.get("config", "default") == "default" else sp["config"]
                C.write_text(os.path.join(d, "config.json"), text)
            audio = sp.get("audio", "audio.wav")
            if audio:
                data = b"" if sp.get("empty") else (b"not audio, just text" if audio.endswith(".txt") else wav_bytes())
                with open(os.path.join(d, audio), "wb") as f:
                    f.write(data)
            # Python 기준 결과
            cands = sorted(f for f in os.listdir(d) if f.lower().startswith("audio."))
            audio_path = os.path.join(d, cands[0]) if cands else ""
            state.reset()
            out = clova_stt.transcribe(audio_path, os.path.join(d, "config.json"))
            err = out["error"] or {}
            result = {"sttJson": out["stt_json"], "sttStage": err.get("stage", ""), "sttError": err.get("reason", "")}
            exp = {"server": server_name, "result": result, "requests": C.norm_requests(state.logs.get(server_name, []))}
            C.write_text(os.path.join(C.TEST, "expected", "step6", name + ".json"), json.dumps(exp, ensure_ascii=False))
            names.append(name)
    finally:
        srv.shutdown()
        srv.server_close()
    return names


# ------------------------------------------------------------------ Step7
def _seg(text, start, end, label=None, key="speaker", edited=None):
    d = {"start": start, "end": end, "text": text}
    if edited is not None:
        d["textEdited"] = edited
    if label is not None:
        d[key] = {"label": label}
    return d


def _resp(*segs, result="COMPLETED"):
    return {"result": result, "segments": list(segs)}


def step7_cases():
    cases = {}
    for sid in C.SIDS:
        cases["real_" + sid] = json.load(open(os.path.join(STT_RAW_DIR, "%s_raw.json" % sid), encoding="utf-8-sig"))
    S = _seg
    cases["greet_first_agent"] = _resp(S("고객센터입니다 무엇을 도와드릴까요", 0, 3000, "1"), S("주문 문의요", 3100, 5000, "2"), S("네 확인해 보겠습니다", 5100, 7000, "1"))
    cases["greet_second_agent"] = _resp(S("여보세요", 0, 1000, "1"), S("고객지원센터입니다 말씀해 주세요", 1100, 3000, "2"), S("주문이 안 와요", 3100, 5000, "1"))
    cases["greet_both"] = _resp(S("상담원 연결 부탁해요", 0, 2000, "1"), S("상담원입니다", 2100, 3000, "2"), S("죄송합니다 확인 후 안내드리겠습니다", 3100, 6000, "2"))
    cases["no_greeting_gap2_agent_second"] = _resp(S("안녕하세요", 0, 1000, "1"), S("죄송합니다 확인 후 안내드리겠습니다", 1100, 4000, "2"), S("네", 4100, 4500, "1"))
    cases["no_greeting_gap2_agent_first"] = _resp(S("죄송합니다 확인해 보겠습니다 안내드리겠습니다", 0, 4000, "1"), S("네", 4100, 4500, "2"))
    cases["no_greeting_equal_scores"] = _resp(S("안녕하세요", 0, 1000, "1"), S("네 말씀하세요", 1100, 2000, "2"))
    cases["no_greeting_first_ahead_by_1"] = _resp(S("확인 후 연락드리겠습니다", 0, 3000, "1"), S("네", 3100, 3500, "2"))
    cases["no_greeting_second_ahead_by_1"] = _resp(S("네", 0, 500, "1"), S("확인 후 연락드리겠습니다", 600, 3000, "2"))
    cases["three_speakers"] = _resp(S("고객센터입니다", 0, 1500, "1"), S("문의요", 1600, 2500, "2"), S("저도 옆에서요", 2600, 3500, "3"), S("네", 3600, 4000, "1"))
    cases["single_speaker"] = _resp(S("혼자 말합니다", 0, 1000, "1"), S("계속 말합니다", 1100, 2000, "1"))
    cases["merge_consecutive"] = _resp(S("고객센터입니다", 0, 1000, "1"), S("무엇을 도와드릴까요", 1100, 2000, "1"), S("네", 2100, 2500, "2"), S("저기요", 2600, 3000, "2"), S("확인해 보겠습니다", 3100, 4000, "1"))
    cases["text_variants"] = _resp(S("  앞뒤 공백  ", 0, 1000, "1"), S("원문", 1100, 2000, "2", edited="  수정본  "), S("", 2100, 2500, "1"), S("   ", 2600, 3000, "2"), S("마지막", 3100, 4000, "1", edited=""))
    cases["label_from_diarization"] = _resp(S("고객센터입니다", 0, 1000, "A", key="diarization"), S("네", 1100, 2000, "B", key="diarization"))
    cases["label_numeric"] = _resp(S("고객센터입니다", 0, 1000, 1), S("네", 1100, 2000, 2), S("감사합니다", 2100, 3000, 1))
    cases["label_missing"] = _resp(S("라벨이 없음", 0, 1000), S("역시 없음", 1100, 2000))
    cases["label_empty_string"] = _resp(S("고객센터입니다", 0, 1000, ""), S("네", 1100, 2000, "2"))
    cases["time_rounding_ties"] = _resp(*[S("t%d" % i, st, st + 5, "AB"[i % 2]) for i, st in enumerate(
        [125, 375, 625, 875, 2125, 5, 15, 25, 35, 2255, 12985, 1005, 2675, 0, 7, 999, 1000, 1234567, 4235, 6125, 8165])])
    cases["time_float_and_string"] = _resp(S("실수 시간", 1234.5, 2345.5, "1"), S("문자열 시간", "1000", "2500", "2"))
    cases["time_missing"] = _resp({"text": "시간 없음", "speaker": {"label": "1"}}, {"text": "여전히 없음", "speaker": {"label": "2"}})
    cases["time_bad_string"] = _resp(S("잘못된 시간", "abc", 1000, "1"))
    cases["time_null"] = _resp(S("널 시간", None, 1000, "1"))
    cases["result_failed"] = {"result": "FAILED", "message": "처리 실패"}
    cases["result_missing"] = {"segments": [S("x", 0, 1, "1")]}
    cases["result_processing"] = {"result": "PROCESSING", "token": "t"}
    cases["segments_missing"] = {"result": "COMPLETED"}
    cases["segments_empty"] = {"result": "COMPLETED", "segments": []}
    cases["segments_all_blank"] = _resp(S("", 0, 1, "1"), S("  ", 1, 2, "2"))
    cases["segments_null"] = {"result": "COMPLETED", "segments": None}
    cases["unicode_and_date_like_text"] = _resp(S("고객센터입니다 2026-11-24T15:30:00+09:00 접수", 0, 2000, "1"), S("😀 이모지 포함 텍스트", 2100, 3000, "2"))
    return cases


def build_step7():
    cases = step7_cases()
    for name, resp in cases.items():
        C.write_text(os.path.join(C.TEST, "step7", name + ".json"), json.dumps(resp, ensure_ascii=False))
        C.write_text(os.path.join(C.TEST, "expected", "step7", name + ".json"), json.dumps(C.expected_step7(resp), ensure_ascii=False))
    return list(cases)
