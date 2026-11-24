"""FastAPI 애플리케이션 진입점.

라우터·미들웨어 등록은 각 기능(C-02 공통 모듈, W-*, R-*)에서 추가한다.
"""

from fastapi import FastAPI


def create_app() -> FastAPI:
    return FastAPI(title="Callcenter AI RPA Backend", version="0.1.0")


app = create_app()
