"""웹 업로드 순수 규칙: 파일명 정규화(normalize_filename), 내용 형식 판정(detect_audio_format)."""

import unicodedata

import pytest

from app.infra.inbox.local import validate_local_name
from app.services.upload_service import detect_audio_format, normalize_filename

_NAME = "20261124_101500_김상담_A산업.mp3"

# ---------------------------------------------------------------- 파일명


def test_keeps_original_name() -> None:
    assert normalize_filename(_NAME) == _NAME


def test_nfd_name_becomes_nfc() -> None:
    nfd = unicodedata.normalize("NFD", _NAME)
    assert nfd != _NAME

    assert normalize_filename(nfd) == _NAME


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/a b.wav", "a b.wav"),
        ("dir/sub/a.wav", "a.wav"),
        ("C:\\Users\\x\\a.wav", "a.wav"),
        ("..\\a.wav", "a.wav"),
    ],
)
def test_keeps_only_last_path_component(raw: str, expected: str) -> None:
    assert normalize_filename(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        ".",
        "..",
        "dir/",
        "a/..",
        *(f"a{ch}b.wav" for ch in ':*?"<>|'),
        "a\x00b.wav",
        "a\x1fb.wav",
        "a\tb.wav",
        " a.wav",
        "a.wav ",
        "a.wav.",
        "a.wav\u3000",
    ],
)
def test_rejects_unusable_name(raw: str | None) -> None:
    assert normalize_filename(raw) is None


def test_length_limit_is_255_utf16_units() -> None:
    assert normalize_filename("가" * 251 + ".wav") == "가" * 251 + ".wav"  # 255
    assert normalize_filename("가" * 252 + ".wav") is None  # 256
    assert normalize_filename("😀" * 126 + ".wav") is None  # 252 + 4 = 256 (이모지는 2단위)


def test_accepted_names_pass_local_writer_check() -> None:
    for raw in (_NAME, "../../etc/a b.wav", "C:\\x\\a.wav", unicodedata.normalize("NFD", _NAME)):
        name = normalize_filename(raw)
        assert name is not None
        validate_local_name(name)  # LocalInboxWriter가 ValueError(→ 500)를 내지 않음


# ---------------------------------------------------------------- 형식 판정


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"RIFF\x24\x08\x00\x00WAVEfmt ", "wav"),
        (b"RIFF\x00\x00\x00\x00WAVE", "wav"),
        (b"ID3\x04\x00\x00\x00\x00\x00\x00", "mp3"),
        (b"\xff\xfb\x90\x64", "mp3"),  # MPEG-1 Layer III
        (b"\xff\xfa\x90\x64", "mp3"),  # MPEG-1 Layer III, CRC 보호
        (b"\xff\xf3\x90\x64", "mp3"),  # MPEG-2 Layer III
        (b"\xff\xf2\x90\x64", "mp3"),
        (b"\xff\xe3\x90\x64", "mp3"),  # MPEG-2.5 Layer III
        (b"\xff\xe2\x90\x64", "mp3"),
    ],
)
def test_detects_supported_format(head: bytes, expected: str) -> None:
    assert detect_audio_format(head) == expected


@pytest.mark.parametrize(
    "head",
    [
        b"",
        b"R",
        b"\xff",
        b"RIFF\x00\x00\x00\x00AVI ",  # RIFF지만 WAVE 아님
        b"RIFF\x00\x00\x00\x00WAV",  # 11바이트
        b"RF64\x00\x00\x00\x00WAVE",
        b"\xff\xf1\x50\x80",  # ADTS AAC (레이어 00)
        b"\xff\xf9\x50\x80",
        b"\xff\xfd\x90\x64",  # MPEG-1 Layer II
        b"\xff\xff\x90\x64",  # MPEG-1 Layer I
        b"\xff\xeb\x90\x64",  # 버전 예약값(01)
        b"\x00\x00\x00\x20ftypM4A ",  # M4A
        b"OggS\x00\x02",
        b"fLaC\x00\x00",
        b"%PDF-1.7",
    ],
)
def test_rejects_other_content(head: bytes) -> None:
    assert detect_audio_format(head) is None
