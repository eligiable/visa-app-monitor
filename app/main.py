"""FastAPI application factory and health endpoints."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.auth.router import router as auth_router
from app.config import Settings
from app.dashboard.router import router as dashboard_router
from app.database.session import create_database_engine, create_session_factory
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)
STATIC_DIRECTORY = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the web application and initialize its database on startup."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime_settings = settings or Settings()
        configure_logging(runtime_settings.log_level)
        engine = create_database_engine(
            runtime_settings.database_url.get_secret_value(),
            engine_options={"pool_pre_ping": True},
        )
        application.state.settings = runtime_settings
        application.state.engine = engine
        application.state.session_factory = create_session_factory(engine)
        logger.info("Web application started")
        try:
            yield
        finally:
            engine.dispose()
            logger.info("Web application stopped")

    application = FastAPI(
        title="eligiable Visa Appointment Monitoring System",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.include_router(auth_router)
    application.include_router(dashboard_router)
    application.mount(
        "/static",
        StaticFiles(directory=STATIC_DIRECTORY),
        name="static",
    )

    @application.middleware("http")
    async def add_security_headers(
        request: Request,
        call_next,
    ) -> Response:
        """Set defensive browser headers and prevent auth response caching."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if request.url.path.startswith("/api/auth/"):
            response.headers["Cache-Control"] = "no-store"
        runtime_settings = getattr(request.app.state, "settings", None)
        if runtime_settings and runtime_settings.session_cookie_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    @application.get("/health/live")
    def liveness() -> dict[str, str]:
        """Report that the web process can serve requests."""
        return {"status": "ok"}

    @application.get("/health/ready")
    def readiness(request: Request) -> Response:
        """Report readiness only when the configured database is reachable."""
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            logger.error("Database readiness check failed")
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable"},
            )
        return JSONResponse(status_code=200, content={"status": "ok"})

    @application.get("/", include_in_schema=False)
    def dashboard_ui() -> Response:
        """Serve the browser-based administrator dashboard."""
        from fastapi.responses import FileResponse

        return FileResponse(STATIC_DIRECTORY / "index.html")

    @application.get("/health")
    def health() -> dict[str, str]:
        """Retain a simple compatibility health endpoint."""
        return {"status": "ok"}

    return application


app = create_app()
