# -*- coding: utf-8 -*-
"""
Step1: CLOVA Speech 호출 (UiPath HTTP Request 폴백 겸 레퍼런스 구현)

사용법
  # 키/음성 없이 구조만 테스트 (더미 응답 사용)
  python clova_stt.py --dummy
  python clova_stt.py --dummy-file ..\\test\\dummy_clova_response_failed.json

  # 실제 호출 (config.json에 키를 넣은 뒤)
  python clova_stt.py --audio ..\\test\\call_01_질의.m4a --raw-out ..\\test\\sample_response.json

UiPath에서 부르는 법 (Python Scope → Load Python Script → Invoke Python Method)
  메서드: run(audio_path, config_path)  → JSON 문자열 반환
  반환 형식: {"success": bool, "error": {"stage","reason"} | null, "stt_json": {...CLOVA 원본 응답...} | null}

주의: 응답 구조(result/segments/text 등)와 엔드포인트는 기억 기반 가정이라
      실제 응답을 받으면 sample_response.json과 대조해 수정할 것. Secret Key는 출력/로그에 남기지 않는다.
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(ROOT, "config.json")
DUMMY_OK = os.path.join(ROOT, "test", "dummy_clova_response.json")
ALLOWED_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".mp4"}  # 지원 포맷은 콘솔 가이드에서 확인


class SttError(Exception):
    def __init__(self, stage, reason):
        super().__init__(reason)
        self.stage = stage
        self.reason = reason


def load_config(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except Exception:
        raise SttError("INPUT", "config.json을 읽을 수 없음(경로/JSON 형식 확인)")
    for k in ("clova_invoke_url", "clova_secret_key"):
        v = str(cfg.get(k, "") or "")
        if not v or v.startswith("여기에_"):
            raise SttError("INPUT", "config.json의 %s 값이 비어 있음" % k)
    return cfg


def build_params(cfg):
    s = cfg.get("stt", {})
    return {
        "language": s.get("language", "ko-KR"),
        "completion": s.get("completion", "sync"),
        "diarization": {
            "enable": True,
            "speakerCountMin": s.get("speaker_count_min", 2),
            "speakerCountMax": s.get("speaker_count_max", 2),
        },
        "noiseFiltering": s.get("noise_filtering", True),
        "fullText": True,
    }


def check_audio(path):
    if not path or not os.path.isfile(path):
        raise SttError("INPUT", "음성 파일이 없음")
    if os.path.getsize(path) == 0:
        raise SttError("INPUT", "빈 파일(0 byte)")
    if os.path.splitext(path)[1].lower() not in ALLOWED_EXT:
        raise SttError("INPUT", "지원하지 않는 파일 형식")


def _poll(requests, base, token, headers, cfg):
    s = cfg.get("stt", {})
    interval = s.get("poll_interval_sec", 5)
    for _ in range(int(s.get("poll_max_count", 60))):
        r = requests.get("%s/recognizer/%s" % (base, token), headers=headers, timeout=30)
        r.raise_for_status()
        d = r.json()
        if d.get("result") in ("COMPLETED", "FAILED"):
            return d
        time.sleep(interval)
    raise SttError("STT", "결과 대기 시간 초과(폴링 한도)")


def call_clova(audio_path, cfg):
    import requests  # pip install requests

    base = cfg["clova_invoke_url"].rstrip("/")
    headers = {"X-CLOVASPEECH-API-KEY": cfg["clova_secret_key"]}
    params = build_params(cfg)
    with open(audio_path, "rb") as f:
        files = {
            "media": (os.path.basename(audio_path), f),
            "params": (None, json.dumps(params, ensure_ascii=False), "application/json"),
        }
        r = requests.post(base + "/recognizer/upload", headers=headers, files=files, timeout=300)
    r.raise_for_status()
    data = r.json()
    if data.get("result") not in ("COMPLETED", "FAILED") and data.get("token"):
        data = _poll(requests, base, data["token"], headers, cfg)
    return data


def transcribe(audio_path="", config_path="", dummy_file=""):
    out = {"success": False, "error": None, "stt_json": None}
    try:
        if dummy_file:
            with open(dummy_file, encoding="utf-8") as f:
                resp = json.load(f)
        else:
            cfg = load_config(config_path or DEFAULT_CONFIG)
            check_audio(audio_path)
            resp = call_clova(audio_path, cfg)
        if resp.get("result") != "COMPLETED":
            raise SttError("STT", "CLOVA 처리 실패: %s" % resp.get("message", "원인 불명"))
        if not resp.get("segments"):
            raise SttError("STT", "인식된 발화가 없음(무음/빈 음성)")
        out["success"] = True
        out["stt_json"] = resp
    except SttError as e:
        out["error"] = {"stage": e.stage, "reason": e.reason}
    except Exception as e:  # 키/URL이 메시지에 섞이지 않도록 종류만 기록
        status = getattr(getattr(e, "response", None), "status_code", None)
        reason = "HTTP %s" % status if status else type(e).__name__
        out["error"] = {"stage": "STT", "reason": "호출 오류(%s)" % reason}
    return out


def run(audio_path, config_path=""):
    """UiPath Invoke Python Method용 진입점. JSON 문자열 반환."""
    return json.dumps(transcribe(audio_path, config_path), ensure_ascii=False)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default="")
    ap.add_argument("--config", default="")
    ap.add_argument("--dummy", action="store_true", help="더미 정상 응답 사용(키·음성 불필요)")
    ap.add_argument("--dummy-file", default="", help="다른 더미 응답 파일 사용")
    ap.add_argument("--out", default="", help="결과(wrapper JSON) 저장 경로")
    ap.add_argument("--raw-out", default="", help="CLOVA 원본 응답만 저장 (sample_response.json용)")
    a = ap.parse_args()
    dummy = a.dummy_file or (DUMMY_OK if a.dummy else "")
    res = transcribe(a.audio, a.config, dummy)
    text = json.dumps(res, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    if a.raw_out and res["stt_json"] is not None:
        with open(a.raw_out, "w", encoding="utf-8") as f:
            json.dump(res["stt_json"], f, ensure_ascii=False, indent=2)
    print(text)


if __name__ == "__main__":
    main()
