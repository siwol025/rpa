"""HTTP `Range` 요청 헤더 해석 (RFC 9110 §14). 단일 바이트 범위만 지원한다.

음성 재생(`GET /api/calls/{id}/audio`)이 쓴다. 로봇 음성 다운로드도 같은 규칙을 쓸 수 있게
공용 위치에 둔다.
"""


class RangeNotSatisfiableError(Exception):
    """범위가 파일 크기를 벗어난다 (HTTP 416). `size`는 `Content-Range: bytes */<size>`에 쓴다."""

    def __init__(self, size: int) -> None:
        self.size = size
        super().__init__(f"size={size}")


def _to_int(text: str) -> int | None:
    # RFC의 1*DIGIT만 허용한다. int()는 " 5"·"+5"·"٥"(비ASCII 숫자)도 받아서 먼저 거른다.
    if not (text.isascii() and text.isdigit()):
        return None
    try:
        return int(text)
    except ValueError:  # 4,300자리 초과 (int 변환 자릿수 한도)
        return None


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """`Range` 헤더를 (시작, 끝) 바이트로 바꾼다. 끝은 포함이고 `size - 1`을 넘지 않게 맞춘다.

    None이면 Range를 무시하고 전체(200)를 보낸다: 헤더 없음, 모르는 단위, 문법 오류,
    다중 범위. 문법은 맞지만 파일 안에 들어오는 바이트가 없으면 RangeNotSatisfiableError.
    """
    if header is None:
        return None
    unit, sep, spec = header.partition("=")
    if not sep or unit.lower() != "bytes" or "," in spec:
        return None
    first, dash, last = spec.strip().partition("-")
    if not dash:
        return None
    if first == "":  # bytes=-N: 마지막 N바이트
        suffix = _to_int(last)
        if suffix is None:
            return None
        if suffix == 0 or size == 0:
            raise RangeNotSatisfiableError(size)
        return (max(size - suffix, 0), size - 1)
    start = _to_int(first)
    end = _to_int(last) if last else None
    if start is None or (last and end is None):
        return None
    if end is not None and end < start:
        return None
    if start >= size:
        raise RangeNotSatisfiableError(size)
    return (start, size - 1 if end is None else min(end, size - 1))
