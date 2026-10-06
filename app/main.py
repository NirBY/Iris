"""FastAPI app factory."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.api import auth, instances, messages, system
from app.config import get_settings
from app.db.engine import make_engine, make_session_factory
from app.db.models import User
from app.ingest import webhooks
from app.logging import setup_logging
from app.security.auth import bootstrap_admin, current_user
from app.version import VERSION

STATIC_DIR = Path(__file__).parent / "static"
_CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
_DOCS_CSP = (
    "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    engine = make_engine()
    app.state.session_factory = make_session_factory(engine)
    async with app.state.session_factory() as session:
        await bootstrap_admin(session, settings)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Iris",
        version=VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            _DOCS_CSP if request.url.path == "/api/docs" else _CSP
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(instances.router)
    app.include_router(messages.router)
    app.include_router(webhooks.router)

    @app.get("/api/docs", include_in_schema=False)
    async def docs(_: Annotated[User, Depends(current_user)]) -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Iris API")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith(("api/", "webhooks/", "metrics")) or path in ("api", "webhooks"):
            raise HTTPException(status_code=404)
        try:
            candidate = (STATIC_DIR / path).resolve()
            is_asset = (
                bool(path) and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents
            )
        except ValueError:  # embedded NUL byte
            raise HTTPException(status_code=404) from None
        if is_asset:
            return FileResponse(candidate)
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "UI not built"}, status_code=404)

    return app


app = create_app()
