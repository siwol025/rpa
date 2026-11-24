# -*- coding: utf-8 -*-
"""
로컬 가짜 CLOVA Speech 서버 (테스트 전용) — 실제 호출 없이 STT 호출 코드를 검증한다.

  python fake_clova.py --port 8765 --raw <정상 응답 JSON 파일>     # 계속 실행 (Studio 테스트용)

경로: /external/v1/<시나리오>/recognizer/upload (POST), /external/v1/<시나리오>/recognizer/<token> (GET)
관리: GET /__log/<시나리오> (받은 요청 기록), GET /__reset (기록·카운터 초기화)
시나리오별 응답은 SCENARIOS 참고. 요청 기록은 (헤더 키 일치 여부, 멀티파트 구성, 파일 해시, params JSON)을 담는다.
"""
import argparse
import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FAKE_KEY = "fake-secret-key-for-test-0001"
QUOTA_MSG = "제공되는 무료 인식 시간을 초과했습니다. 추가 작업 등록을 위해서는 새로운 도메인을 생성해 주세요."

# 시나리오 -> 업로드 응답 종류
SCENARIOS = {
    "ok_sync", "ok_async", "poll_timeout", "poll_http_error", "clova_failed", "clova_failed_nomsg", "no_segments",
    "http_401", "http_500", "bad_json", "not_object", "processing_no_token", "custom_params", "ok_sync_trailing_slash",
    "by_name",  # 업로드한 파일 이름의 접두어로 결과를 정함 (폴더 처리 테스트용)
}


def parse_multipart(content_type, body):
    m = re.search(r'boundary=("?)([^";]+)\1', content_type or "")
    if not m:
        return []
    boundary = ("--" + m.group(2)).encode()
    parts = []
    for chunk in body.split(boundary):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        head, _, data = chunk.partition(b"\r\n\r\n")
        headers = {}
        for line in head.decode("utf-8", "replace").split("\r\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        disp = headers.get("content-disposition", "")
        name = re.search(r'name="([^"]*)"', disp)
        fn = re.search(r'filename="([^"]*)"', disp)
        part = {"name": name.group(1) if name else None, "filename": fn.group(1) if fn else None,
                "content_type": (headers.get("content-type") or "").split(";")[0].strip().lower(),
                "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        if part["name"] == "params":
            try:
                part["json"] = json.loads(data.decode("utf-8"))
            except Exception:  # noqa: BLE001
                part["json"] = None
        parts.append(part)
    return parts


class State:
    def __init__(self, raw_path, raw_high_path=None):
        self.raw = json.load(open(raw_path, encoding="utf-8-sig"))
        self.raw_high = json.load(open(raw_high_path, encoding="utf-8-sig")) if raw_high_path else None
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.logs = {}
            self.polls = {}


def make_handler(state):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj=None, raw=None):
            data = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _route(self):
            m = re.match(r"^/external/v1/([^/]+)(/recognizer/.+)$", self.path)
            return (m.group(1), m.group(2)) if m else (None, None)

        def _log(self, sc, entry):
            with state.lock:
                state.logs.setdefault(sc, []).append(entry)

        def do_GET(self):
            if self.path == "/__reset":
                state.reset()
                return self._send(200, {"ok": True})
            m = re.match(r"^/__log/([^/]+)$", self.path)
            if m:
                with state.lock:
                    return self._send(200, state.logs.get(m.group(1), []))
            sc, tail = self._route()
            if sc is None or sc.split("__")[0] not in SCENARIOS:
                return self._send(404, {"error": "unknown scenario"})
            kind = sc.split("__")[0]
            self._log(sc, {"method": "GET", "tail": "/recognizer/<token>" if tail.startswith("/recognizer/") and tail != "/recognizer/upload" else tail,
                           "key_ok": self.headers.get("X-CLOVASPEECH-API-KEY") == FAKE_KEY})
            with state.lock:
                n = state.polls.get(sc, 0) + 1
                state.polls[sc] = n
            if kind == "ok_async":
                return self._send(200, state.raw if n >= 3 else {"result": "PROCESSING", "token": "tok-" + kind})
            if kind == "poll_http_error":
                return self._send(503, {"error": "unavailable"})
            return self._send(200, {"result": "PROCESSING", "token": "tok-" + kind})  # poll_timeout 등

        def do_POST(self):
            sc, tail = self._route()
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n)
            if sc is None or sc.split("__")[0] not in SCENARIOS or tail != "/recognizer/upload":
                return self._send(404, {"error": "unknown route"})
            kind = sc.split("__")[0]
            parts = parse_multipart(self.headers.get("Content-Type"), body)
            self._log(sc, {"method": "POST", "tail": tail, "key_ok": self.headers.get("X-CLOVASPEECH-API-KEY") == FAKE_KEY, "parts": parts})
            if kind == "by_name":
                fname = next((p["filename"] for p in parts if p["name"] == "media"), "") or ""
                low = fname.lower()
                if low.startswith("clovafail"):
                    return self._send(200, {"result": "FAILED", "message": QUOTA_MSG})
                if low.startswith("http500"):
                    return self._send(500, {"error": "server error"})
                if low.startswith("nosegs"):
                    return self._send(200, {"result": "COMPLETED", "segments": []})
                if low.startswith("low_") or state.raw_high is None:
                    return self._send(200, state.raw)       # 화자 1명(LOW)인 응답
                return self._send(200, state.raw_high)      # 화자 2명(HIGH)인 응답
            if kind in ("ok_sync", "custom_params", "ok_sync_trailing_slash"):
                return self._send(200, state.raw)
            if kind in ("ok_async", "poll_timeout", "poll_http_error"):
                return self._send(200, {"result": "PROCESSING", "token": "tok-" + kind})
            if kind == "processing_no_token":
                return self._send(200, {"result": "PROCESSING"})
            if kind == "clova_failed":
                return self._send(200, {"result": "FAILED", "message": QUOTA_MSG})
            if kind == "clova_failed_nomsg":
                return self._send(200, {"result": "FAILED"})
            if kind == "no_segments":
                return self._send(200, {"result": "COMPLETED", "segments": []})
            if kind == "http_401":
                return self._send(401, {"error": "unauthorized"})
            if kind == "http_500":
                return self._send(500, {"error": "server error"})
            if kind == "bad_json":
                return self._send(200, raw=b"this is not json")
            if kind == "not_object":
                return self._send(200, raw=b"[1, 2, 3]")
            return self._send(500, {"error": "unhandled"})

    return H


def start_server(port, raw_path, raw_high_path=None):
    state = State(raw_path, raw_high_path)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--raw", required=True, help="정상(COMPLETED) 응답으로 돌려줄 JSON 파일")
    ap.add_argument("--raw-high", default="", help="by_name 시나리오에서 화자 2명(HIGH) 응답으로 돌려줄 JSON 파일")
    a = ap.parse_args()
    srv, _ = start_server(a.port, a.raw, a.raw_high or None)
    print("가짜 CLOVA 서버 실행 중: http://127.0.0.1:%d  (Ctrl+C 로 종료)" % a.port, flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
