# -*- coding: utf-8 -*-
"""OpenAI 폴백 모듈 테스트 — 가짜 로컬 서버를 쓰므로 키·네트워크 불필요:  python test_openai_llm.py"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyze
import openai_llm

passed = 0


def check(name, cond):
    global passed
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)
    passed += 1


SEEN = []
MODE = {"m": "ok"}
GOOD = analyze.mock_llm("s", "INPUT:\n[상담원] 안녕하세요\n[고객] 배송이 늦어서 불만입니다 언제 오나요? 환불 보상 해주세요 항의합니다\nOUTPUT:")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
        SEEN.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        m = MODE["m"]
        if m == "401":
            return self._send(401, {"error": {"message": "Incorrect API key provided: sk-TESTKEY123"}})
        if m == "temp" and "temperature" in body:
            return self._send(400, {"error": {"message": "Unsupported value: 'temperature' does not support 0"}})
        fr = "length" if m == "length" else "stop"
        self._send(200, {"choices": [{"message": {"content": GOOD}, "finish_reason": fr}]})

    def _send(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d/v1" % srv.server_port
cfg = {"api_key": "sk-TESTKEY123", "model": "test-model", "temperature": 0, "max_output_tokens": 800, "base_url": URL}

llm = openai_llm.make_llm(cfg)
out = llm("SYS", "USR")
req = SEEN[-1]
check("정상 응답 텍스트 반환", out == GOOD)
check("엔드포인트 /chat/completions + Bearer 키", req["path"] == "/v1/chat/completions" and req["auth"] == "Bearer sk-TESTKEY123")
check("system/user 메시지 순서", [m["role"] for m in req["body"]["messages"]] == ["system", "user"] and req["body"]["messages"][1]["content"] == "USR")
check("모델·온도·토큰 상한 전달", req["body"]["model"] == "test-model" and req["body"]["temperature"] == 0 and req["body"]["max_completion_tokens"] == 800)
check("json_mode 기본 꺼짐", "response_format" not in req["body"])
check("analyze.analyze에 그대로 연결(검증 통과)", analyze.analyze("[상담원] 안녕하세요\n[고객] 배송 불만 환불 보상 항의", llm=llm)[1] is None)

MODE["m"] = "temp"; n = len(SEEN)
out = openai_llm.make_llm(cfg)("S", "U")
check("temperature 거부 모델: 빼고 재시도해 성공", out == GOOD and len(SEEN) == n + 2 and "temperature" not in SEEN[-1]["body"])

MODE["m"] = "401"
try:
    openai_llm.make_llm(cfg)("S", "U")
    check("401 → LlmError", False)
except openai_llm.LlmError as e:
    check("401 → LlmError, 키 안내", "401" in str(e) and "키" in str(e))
    check("오류 메시지에 키가 노출되지 않음", "sk-TESTKEY123" not in str(e))

MODE["m"] = "length"
try:
    openai_llm.make_llm(cfg)("S", "U")
    check("잘린 출력 → LlmError", False)
except openai_llm.LlmError as e:
    check("잘린 출력(finish_reason=length) 감지", "잘림" in str(e))
MODE["m"] = "ok"

bad_cfg = dict(cfg, base_url="http://127.0.0.1:1/v1", timeout_sec=3)
try:
    openai_llm.make_llm(bad_cfg)("S", "U")
    check("연결 실패 → LlmError", False)
except openai_llm.LlmError as e:
    check("연결 실패 → LlmError", "연결 실패" in str(e) or "시간 초과" in str(e))

# 설정 읽기
def write(obj):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(obj, f); f.close()
    return f.name

def expect_error(obj, frag, label):
    p = write(obj)
    os.environ.pop("OPENAI_API_KEY", None)
    try:
        openai_llm.load_openai_config(p)
        check(label, False)
    except openai_llm.LlmError as e:
        check(label, frag in str(e))
    finally:
        os.remove(p)

expect_error({}, "OpenAI 키", "설정 없음 → 안내")
expect_error({"openai": {"api_key": "여기에_키", "model": "m"}}, "OpenAI 키", "자리표시자 키 거부")
expect_error({"openai": {"api_key": "k"}}, "openai.model", "모델 이름 없음 → 안내")
p = write({"openai": {"api_key": "k", "model": "m"}})
check("키·모델이 있으면 로드", openai_llm.load_openai_config(p)["model"] == "m"); os.remove(p)
p = write({"openai": {"model": "m"}}); os.environ["OPENAI_API_KEY"] = "envkey"
check("api_key가 없으면 환경변수 사용", openai_llm.load_openai_config(p)["api_key"] == "envkey"); os.remove(p); os.environ.pop("OPENAI_API_KEY")

print("\n통과: %d" % passed)
