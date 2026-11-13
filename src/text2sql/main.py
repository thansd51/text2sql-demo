from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from text2sql.api import datasources, health, text_to_sql
from text2sql.api.errors import register_error_handlers
from text2sql.api.security import require_access_key
from text2sql.config import Settings, check_auth_settings, get_settings
from text2sql.llm import LLMClient
from text2sql.pipeline import SqlGenerator
from text2sql.semantic import Registry
from text2sql.startup import create_generator, load_registry


def create_app(
    settings: Settings | None = None,
    *,
    registry: Registry | None = None,
    llm: LLMClient | None = None,
) -> FastAPI:
    """앱을 만든다. registry와 llm을 주면(테스트) 시작할 때 만들지 않고 그대로 쓴다.

    주지 않으면 앱이 시작될 때(lifespan) 파일에서 레지스트리를 읽고 LLM 클라이언트를
    만든다. 이때 메타데이터에 문제가 있으면 시작에 실패한다.
    """
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        check_auth_settings(settings)
        if app.state.registry is None:
            app.state.registry = load_registry(settings)
        if app.state.generator is None:
            app.state.generator = create_generator(settings)
        yield

    # API 문서(/docs, /redoc, /openapi.json)는 접속 키 없이 열리므로 인증을 켠 배포에서는 닫는다.
    # 접속 키를 끈 로컬 개발에서만 연다.
    docs = settings.auth_disabled
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.registry = registry
    app.state.generator = (
        SqlGenerator(llm, settings.max_repair_attempts, max_rows=settings.max_rows)
        if llm is not None
        else None
    )
    register_error_handlers(app)
    # /health는 접속 키 없이 열어 둔다 (배포 환경의 헬스체크용). 나머지 API는 접속 키가 필요하다.
    protected = [Depends(require_access_key)]
    app.include_router(health.router)
    app.include_router(text_to_sql.router, dependencies=protected)
    app.include_router(datasources.router, dependencies=protected)
    # 반드시 마지막에 마운트한다. 앞의 API 경로가 먼저 맞아야 하기 때문이다.
    dist = settings.frontend_dist_dir
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


# 실행 명령(uvicorn text2sql.main:app)을 위한 인스턴스
app = create_app()
