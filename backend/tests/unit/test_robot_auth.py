"""R-01 로봇 API 접근 통제 (X-API-Key 401, 호출 IP 403)."""

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app

KEY = "robot-key-current"
NEXT_KEY = "robot-key-next"
ROBOT_IP = "10.0.0.5"


def _client(*, ip: str | None = ROBOT_IP, **overrides: Any) -> TestClient:
    settings: dict[str, Any] = {"robot_api_keys": [KEY], "robot_allowed_ips": [ROBOT_IP]}
    settings.update(overrides)
    app: FastAPI = create_app(Settings(_env_file=None, **settings))

    @app.get("/api/robot/ping")
    def robot_ping() -> dict[str, str]:
        return {"ok": "robot"}

    @app.get("/api/robotics")  # 접두사만 같은 다른 경로는 대상이 아니다
    def other_path() -> dict[str, str]:
        return {"ok": "other"}

    # TestClient의 호출 IP는 기본값이 "testclient"(IP가 아님)라 테스트마다 지정한다.
    return TestClient(app, client=(ip, 50000) if ip else None)  # type: ignore[arg-type]


def _headers(key: str | None = KEY) -> dict[str, str]:
    return {"X-API-Key": key} if key is not None else {}


def test_valid_key_and_allowed_ip_pass() -> None:
    response = _client().get("/api/robot/ping", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {"ok": "robot"}


def test_missing_key_is_401_with_error_format() -> None:
    response = _client().get("/api/robot/ping")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
    assert "X-Request-Id" in response.headers


@pytest.mark.parametrize("key", ["wrong", "", KEY + "x", KEY[:-1], KEY.upper()])
def test_wrong_key_is_401(key: str) -> None:
    response = _client().get("/api/robot/ping", headers=_headers(key))

    assert response.status_code == 401


def test_two_keys_are_accepted_at_the_same_time() -> None:
    client = _client(robot_api_keys=[KEY, NEXT_KEY])

    assert client.get("/api/robot/ping", headers=_headers(KEY)).status_code == 200
    assert client.get("/api/robot/ping", headers=_headers(NEXT_KEY)).status_code == 200
    assert client.get("/api/robot/ping", headers=_headers("old-key")).status_code == 401


def test_no_configured_keys_rejects_everything() -> None:
    client = _client(robot_api_keys=[])

    assert client.get("/api/robot/ping", headers=_headers(KEY)).status_code == 401
    assert client.get("/api/robot/ping", headers=_headers("")).status_code == 401


def test_ip_not_allowed_is_403() -> None:
    response = _client(ip="10.0.0.99").get("/api/robot/ping", headers=_headers())

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_IP"


def test_no_configured_ips_rejects_everything() -> None:
    assert (
        _client(robot_allowed_ips=[]).get("/api/robot/ping", headers=_headers()).status_code == 403
    )


def test_wrong_key_wins_over_wrong_ip() -> None:
    # 허용되지 않은 IP에게 "IP 제한이 있다"는 사실을 먼저 알려주지 않는다.
    response = _client(ip="203.0.113.9").get("/api/robot/ping", headers=_headers("wrong"))

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("allowed", "ip", "status"),
    [
        (["10.0.0.0/24"], "10.0.0.200", 200),
        (["10.0.0.0/24"], "10.0.1.1", 403),
        (["127.0.0.1", "10.0.0.5"], "127.0.0.1", 200),
        (["::1"], "::1", 200),
        (["2001:db8::/32"], "2001:db8::7", 200),
        (["2001:db8::/32"], "10.0.0.5", 403),
        (["10.0.0.5"], "::ffff:10.0.0.5", 200),  # IPv4-mapped IPv6
    ],
)
def test_ip_allow_list_supports_cidr_and_ipv6(allowed: list[str], ip: str, status: int) -> None:
    response = _client(ip=ip, robot_allowed_ips=allowed).get("/api/robot/ping", headers=_headers())

    assert response.status_code == status


def test_unknown_client_is_403() -> None:
    assert _client(ip=None).get("/api/robot/ping", headers=_headers()).status_code == 403


def test_only_robot_paths_are_guarded() -> None:
    client = _client(ip="203.0.113.9")

    assert client.get("/api/robotics").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/api/calls/1").status_code != 401


def test_unknown_robot_path_is_guarded_too() -> None:
    # 아직 없는 로봇 경로도 인증 전에는 404로 존재 여부를 알려주지 않는다.
    client = _client()

    assert client.get("/api/robot/nope").status_code == 401
    assert client.get("/api/robot/nope", headers=_headers()).status_code == 404


def test_failure_is_logged_without_the_key(capsys: pytest.CaptureFixture[str]) -> None:
    client = _client(ip="203.0.113.9")

    client.get("/api/robot/ping", headers=_headers(KEY))

    out = capsys.readouterr().out
    failures = [
        json.loads(line)
        for line in out.splitlines()
        if line.strip() and json.loads(line).get("event") == "robot_auth_failed"
    ]
    assert len(failures) == 1
    assert failures[0]["reason"] == "ip"
    assert failures[0]["client_ip"] == "203.0.113.9"
    assert KEY not in out


class TestSettings:
    def test_comma_separated_env_values_are_split(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROBOT_API_KEYS", " a , b ")
        monkeypatch.setenv("ROBOT_ALLOWED_IPS", "10.0.0.5, 192.168.0.0/24")

        settings = Settings(_env_file=None)

        assert settings.robot_api_keys == ["a", "b"]
        assert settings.robot_allowed_ips == ["10.0.0.5", "192.168.0.0/24"]

    def test_defaults_are_empty_so_robot_api_is_closed(self) -> None:
        settings = Settings(_env_file=None)

        assert settings.robot_api_keys == []
        assert settings.robot_allowed_ips == []

    def test_more_than_two_keys_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="최대 2개"):
            Settings(_env_file=None, robot_api_keys=["a", "b", "c"])

    def test_invalid_ip_is_rejected_at_startup(self) -> None:
        with pytest.raises(ValidationError, match="올바르지 않은 IP"):
            Settings(_env_file=None, robot_allowed_ips=["10.0.0.5", "not-an-ip"])
