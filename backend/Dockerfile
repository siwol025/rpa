# 운영 이미지 (O-01): 멀티 스테이지, non-root.
# 빌드: docker build -t callcenter-api backend
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# 의존성만 먼저 설치해 레이어 캐시를 활용한다 (잠금 파일 그대로, 개발 의존성 제외).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AUDIO_STORAGE_ROOT=/data/audio

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
 && mkdir -p /data/audio \
 && chown -R app:app /data

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
COPY --chown=app:app templates ./templates

USER app
EXPOSE 8000

# 시작할 때 마이그레이션을 적용한 뒤 서버를 띄운다 (적용 실패 시 컨테이너가 시작되지 않는다).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
