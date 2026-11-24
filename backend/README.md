# Callcenter AI RPA — Backend

FastAPI + PostgreSQL 16. 설계 문서는 [`docs/`](docs/) 참조.

| 문서 | 위치 |
|---|---|
| 아키텍처 | `docs/architecture/architecture.md` |
| 기술 스택 | `docs/tech-stack/back_stack.md` |
| 리서치 | `docs/researchs/research.md` |
| 기능 목록·분담 | `docs/features/features.md` |
| API 규약 | `docs/api/convention.md` |
| OpenAPI (팀 간 계약) | `docs/api/openapi.json` |

## 준비물

- [uv](https://docs.astral.sh/uv/) (Python 3.12 은 uv 가 `.python-version` 기준으로 설치)
- Docker Desktop (개발용 DB·compose 실행, testcontainers)

## 로컬 개발

```bash
cd backend
uv sync                      # 가상환경 + 의존성 설치 (uv.lock 기준)
cp .env.example .env
uv run pre-commit install --config ../.pre-commit-config.yaml

uv run uvicorn app.main:app --reload    # http://localhost:8000/docs
```

### Docker Compose (api + db + adminer)

```bash
# 레포 루트에서
docker compose -f deploy/docker-compose.dev.yml up --build
```

| 서비스 | 주소 |
|---|---|
| API (hot reload) | http://localhost:8000/docs |
| PostgreSQL | localhost:5432 (callcenter / callcenter) |
| Adminer | http://localhost:8080 (서버: `db`) |

## 검사

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest                     # 전체
uv run pytest -m "not integration"   # Docker 없이 실행 가능한 테스트만
```

### OpenAPI 갱신

요청·응답 스키마나 라우트를 바꾸면 다시 생성해 같은 커밋에 포함한다(최신이 아니면 `pytest`가 실패한다).

```bash
uv run python -m scripts.export_openapi
```
