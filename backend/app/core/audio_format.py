"""음성 파일 형식 판정 (웹 업로드·로봇 등록 공용).

확장자·클라이언트 Content-Type은 믿지 않고 파일 앞부분(매직 바이트)으로 형식을 정한다.
"""

from app.core.config import AudioExtension

HEAD_BYTES = 12  # 매직 바이트 판정에 읽는 앞부분 길이

# 형식별 정규 MIME. 클라이언트가 보낸 Content-Type 대신 이 값을 쓴다.
CANONICAL_MIME: dict[AudioExtension, str] = {"wav": "audio/wav", "mp3": "audio/mpeg"}


def detect_audio_format(head: bytes) -> AudioExtension | None:
    """앞부분으로 형식을 판정한다. WAV = RIFF…WAVE, MP3 = ID3 태그 또는 Layer III 프레임 동기."""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:3] == b"ID3":
        return "mp3"
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:
        version = (head[1] >> 3) & 0b11  # 01은 예약값
        layer = (head[1] >> 1) & 0b11  # 01 = Layer III (00이면 ADTS AAC)
        if version != 0b01 and layer == 0b01:
            return "mp3"
    return None
