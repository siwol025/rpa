# -*- coding: utf-8 -*-
"""
GenAI 폴백: OpenAI Chat Completions 호출 (UiPath Content Generation을 쓰지 못할 때)

analyze.analyze(full_text, llm=...)에 그대로 넣을 수 있는 llm(system, user) -> str 함수를 만든다.

설정 (config.json — .gitignore 제외 대상, 키는 코드·로그·결과 JSON에 넣지 않는다)
  "openai": {
    "api_key": "...",            # 없으면 환경변수 OPENAI_API_KEY 사용
    "model": "사용할 모델 이름",  # 필수 (기본값 없음)
    "temperature": 0,            # 선택. 이 파라미터를 받지 않는 모델이면 자동으로 빼고 재시도
    "max_output_tokens": 1500,   # 선택 (기본 1500). 출력 JSON이 잘리지 않을 만큼
    "timeout_sec": 90,           # 선택 (기본 90)
    "json_mode": false,          # 선택. true면 response_format=json_object (프롬프트 단독 성능을 보려면 false)
    "base_url": "https://api.openai.com/v1"   # 선택. OpenAI 호환 서버 지정 (예: Groq "https://api.groq.com/openai/v1")
  }
"""
import json
import os
import time

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class LlmError(Exception):
    """OpenAI 호출 실패. 메시지에 키가 들어가지 않는다."""


def load_openai_config(config_path=None):
    """config.json의 openai 항목을 읽어 검증한 dict를 돌려준다."""
    path = config_path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
    try:
        with open(path, encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except Exception:
        raise LlmError("config.json을 읽을 수 없음(경로/JSON 형식 확인)")
    o = dict(cfg.get("openai") or {})
    key = str(o.get("api_key") or os.environ.get("OPENAI_API_KEY") or "")
    if not key or key.startswith("여기에_") or key.startswith("<"):
        raise LlmError("OpenAI 키가 없음: config.json의 openai.api_key 또는 환경변수 OPENAI_API_KEY를 채워 주세요")
    model = str(o.get("model") or "")
    if not model or model.startswith("<"):
        raise LlmError("config.json의 openai.model(사용할 모델 이름)을 채워 주세요")
    o["api_key"], o["model"] = key, model
    return o


def _post(requests, url, key, body, timeout):
    return requests.post(url, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                         data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=timeout)


def make_llm(o):
    """o: load_openai_config() 결과. 반환: llm(system, user) -> 응답 텍스트."""
    import requests  # pip install requests

    base = str(o.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    url = base + "/chat/completions"
    timeout = float(o.get("timeout_sec", 90))

    def llm(system, user):
        body = {"model": o["model"],
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_completion_tokens": int(o.get("max_output_tokens", 1500))}
        if o.get("temperature") is not None:
            body["temperature"] = o["temperature"]
        if o.get("json_mode"):
            body["response_format"] = {"type": "json_object"}
        try:
            r = _post(requests, url, o["api_key"], body, timeout)
            # 일부 모델은 temperature를 받지 않는다 → 빼고 한 번 더
            if r.status_code == 400 and "temperature" in body and "temperature" in r.text:
                body.pop("temperature")
                r = _post(requests, url, o["api_key"], body, timeout)
            # 무료 API(Groq 등)의 분당 한도 초과: 안내된 시간만큼 기다렸다 최대 2번 재시도 (크레딧 부족 오류는 재시도 안 함)
            for _ in range(2):
                if r.status_code != 429 or "credit" in r.text.lower():
                    break
                try:
                    wait = float(r.headers.get("retry-after") or 20)
                except ValueError:
                    wait = 20.0
                time.sleep(min(max(wait, 1.0), 60.0))
                r = _post(requests, url, o["api_key"], body, timeout)
        except requests.exceptions.Timeout:
            raise LlmError("OpenAI 응답 시간 초과(%ss)" % int(timeout))
        except requests.exceptions.RequestException as e:
            raise LlmError("OpenAI 연결 실패(%s)" % type(e).__name__)
        if r.status_code != 200:
            try:
                msg = r.json().get("error", {}).get("message", "")
            except Exception:  # noqa: BLE001
                msg = ""
            hint = {401: "키가 올바르지 않음", 403: "권한 없음", 404: "모델 이름 확인", 429: "한도 초과/요청 과다"}.get(r.status_code, "")
            raise LlmError("OpenAI 오류 HTTP %d%s%s" % (r.status_code, " (%s)" % hint if hint else "",
                                                       ": " + msg.replace(o["api_key"], "***")[:300] if msg else ""))
        try:
            choice = r.json()["choices"][0]
            text = choice["message"]["content"]
        except Exception:  # noqa: BLE001
            raise LlmError("OpenAI 응답 형식을 해석할 수 없음")
        if choice.get("finish_reason") == "length":
            raise LlmError("출력이 max_output_tokens에서 잘림(finish_reason=length) — max_output_tokens를 늘려 주세요")
        return text or ""

    return llm
