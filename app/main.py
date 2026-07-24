from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from redis import Redis
from sqlalchemy import text

from app.api.ats import router as ats_router
from app.api.jobs import router as jobs_router
from app.api.resume_builder import router as resume_builder_router
from app.api.resumes import router as resumes_router
from app.api.tailoring import router as tailoring_router
from app.core.config import settings
from app.core.db import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    yield
    await app.state.arq_pool.aclose()


app = FastAPI(title="CareerForge", lifespan=lifespan)

app.include_router(resumes_router, prefix="/resumes", tags=["resumes"])
app.include_router(resume_builder_router, prefix="/resume-builder", tags=["resume-builder"])
app.include_router(ats_router, prefix="/ats", tags=["ats"])
app.include_router(tailoring_router, prefix="/tailoring", tags=["tailoring"])
app.include_router(jobs_router, prefix="/jobs", tags=["jobs"])


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
