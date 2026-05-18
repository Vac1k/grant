from celery import Celery

from grant_tool.config import get_settings

settings = get_settings()

celery_app = Celery(
    "grant_tool",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_track_started=True,
    timezone="Europe/Berlin",
)


@celery_app.task(name="grant_tool.healthcheck")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
