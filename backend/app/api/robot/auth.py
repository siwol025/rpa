"""로봇 API 접근 통제 미들웨어 (R-01).

`/api/robot/*` 요청에만 적용한다. 라우트마다 의존성을 붙이는 대신 경로 기준으로 막아,
이후 추가되는 로봇 라우트가 인증을 빠뜨려도 열리지 않게 한다.

1. `X-API-Key` 검증 → 실패 401. 키는 최대 2개를 동시에 허용한다(키 교체 기간).
2. 호출 IP가 `ROBOT_ALLOWED_IPS`(IP·CIDR)에 있는지 확인 → 실패 403.

설정이 비어 있으면 모든 요청을 거절한다. 키 값은 로그·응답에 남기지 않는다.
"""

import hmac
import ipaddress
from collections.abc import Sequence

import structlog
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import ErrorCode, error_response

API_KEY_HEADER = "X-API-Key"
ROBOT_PATH_PREFIX = "/api/robot"

_log = structlog.stdlib.get_logger("app.auth")

type Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def _is_robot_path(path: str) -> bool:
    return path == ROBOT_PATH_PREFIX or path.startswith(ROBOT_PATH_PREFIX + "/")


class RobotAuthMiddleware:
    def __init__(
        self, app: ASGIApp, *, api_keys: Sequence[str], allowed_ips: Sequence[str]
    ) -> None:
        self.app = app
        self._keys = [key.encode() for key in api_keys]
        self._networks: list[Network] = [
            ipaddress.ip_network(item, strict=False) for item in allowed_ips
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_robot_path(scope["path"]):
            await self.app(scope, receive, send)
            return

        client_ip = self._client_ip(scope)

        if not self._valid_key(Headers(scope=scope).get(API_KEY_HEADER)):
            _log.warning("robot_auth_failed", reason="api_key", client_ip=client_ip)
            await error_response(ErrorCode.UNAUTHORIZED)(scope, receive, send)
            return

        if not self._allowed_ip(client_ip):
            _log.warning("robot_auth_failed", reason="ip", client_ip=client_ip)
            await error_response(ErrorCode.FORBIDDEN_IP)(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _valid_key(self, provided: str | None) -> bool:
        if not provided or not self._keys:
            return False
        candidate = provided.encode()
        # 모든 키와 비교해 어느 키가 맞았는지에 따라 걸리는 시간이 달라지지 않게 한다.
        matches = [hmac.compare_digest(candidate, key) for key in self._keys]
        return any(matches)

    def _allowed_ip(self, client_ip: str | None) -> bool:
        if client_ip is None:
            return False
        try:
            address = ipaddress.ip_address(client_ip)
        except ValueError:
            return False
        # IPv4-mapped IPv6(::ffff:1.2.3.4)는 IPv4로 풀어서 비교한다.
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        return any(
            address in network for network in self._networks if network.version == address.version
        )

    @staticmethod
    def _client_ip(scope: Scope) -> str | None:
        client = scope.get("client")
        return str(client[0]) if client else None
