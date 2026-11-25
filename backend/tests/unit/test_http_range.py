"""Range 헤더 해석 (RFC 9110 §14). 크기 S = 1000 기준 경계 사례 표."""

import pytest

from app.core.http_range import RangeNotSatisfiableError, parse_range

S = 1000


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("bytes=0-", (0, S - 1)),
        ("bytes=0-0", (0, 0)),
        ("bytes=100-", (100, S - 1)),
        ("bytes=100-199", (100, 199)),
        ("bytes=999-999", (999, 999)),
        ("bytes=0-99999999", (0, S - 1)),  # 끝이 크기를 넘으면 마지막 바이트로 맞춤
        ("bytes=-10", (S - 10, S - 1)),
        ("bytes=-1000", (0, S - 1)),
        ("bytes=-99999999", (0, S - 1)),  # suffix가 크기보다 크면 전체
        ("BYTES=0-1", (0, 1)),  # 단위 이름은 대소문자 무시
        ("bytes= 0-1 ", (0, 1)),  # 범위 목록 앞뒤 공백(OWS)
        ("bytes=0-" + "9" * 5000, None),  # int 자릿수 한도 초과 → 무효
    ],
)
def test_parse_range(header: str | None, expected: tuple[int, int] | None) -> None:
    assert parse_range(header, S) == expected


@pytest.mark.parametrize(
    "header",
    [
        "bytes=5-2",  # 시작 > 끝
        "bytes=abc",
        "bytes=",
        "bytes=-",
        "bytes=1-2-3",
        "bytes=--5",
        "bytes=+5-",
        "bytes=0-+5",
        "bytes=0 -1",
        "bytes=٥-",  # 비ASCII 숫자
        "items=0-1",  # 모르는 단위 (RFC MUST 무시)
        "bytes 0-1",  # '=' 없음
        "bytes=0-1,5-6",  # 다중 범위
        "bytes=0-1, 5-6",
        "",
    ],
)
def test_invalid_or_multi_range_is_ignored(header: str) -> None:
    assert parse_range(header, S) is None


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=5000-6000", "bytes=-0"])
def test_unsatisfiable_range_raises_with_size(header: str) -> None:
    with pytest.raises(RangeNotSatisfiableError) as exc_info:
        parse_range(header, S)

    assert exc_info.value.size == S


@pytest.mark.parametrize("header", ["bytes=0-", "bytes=-1"])
def test_empty_file_is_unsatisfiable(header: str) -> None:
    with pytest.raises(RangeNotSatisfiableError):
        parse_range(header, 0)


def test_no_header_on_empty_file_is_full() -> None:
    assert parse_range(None, 0) is None
