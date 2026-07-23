from fastapi import FastAPI
from redis import Redis
from sqlalchemy import text

from app.api.resumes import router as resumes_router
from app.core.config import settings
from app.core.db import engine

app = FastAPI(title="CareerForge")

app.include_router(resumes_router, prefix="/resumes", tags=["resumes"])


@app.get("/health")
def health() -> dict:
    status = {"status": "ok", "app_env": settings.app_env, "database": "ok", "redis": "ok"}

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        status["status"] = "degraded"
        status["database"] = f"error: {exc}"

    try:
        redis_client = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        redis_client.ping()
    except Exception as exc:
        status["status"] = "degraded"
        status["redis"] = f"error: {exc}"

    return status
