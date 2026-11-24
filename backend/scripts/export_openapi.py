"""OpenAPI 스키마를 docs/api/openapi.json으로 내보낸다.

실행: cd backend && uv run python -m scripts.export_openapi
"""

import json
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.main import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.json"


def build_openapi() -> dict[str, Any]:
    # 개발자 .env와 무관하게 같은 결과가 나오도록 기본 설정으로 만든다.
    return create_app(Settings(_env_file=None)).openapi()


def main() -> None:
    text = json.dumps(build_openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OPENAPI_PATH}")


if __name__ == "__main__":
    main()
