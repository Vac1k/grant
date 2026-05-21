from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from grant_tool.api.routes.health import router as health_router
from grant_tool.config import get_settings
from grant_tool.dashboard import router as dashboard_router


def create_app() -> FastAPI:
    settings = get_settings()
    static_dir = Path(__file__).resolve().parent / "static"
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="REST API and internal dashboard for AI-assisted grant matching.",
    )

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(dashboard_router)

    return app


app = create_app()
