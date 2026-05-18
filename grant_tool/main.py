from fastapi import FastAPI

from grant_tool.api.routes.health import router as health_router
from grant_tool.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="REST API and internal dashboard for AI-assisted grant matching.",
    )

    app.include_router(health_router, prefix="/api/v1")

    @app.get("/", tags=["system"])
    def root() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "status": "ok",
            "docs": "/docs",
            "health": "/api/v1/health",
        }

    return app


app = create_app()
