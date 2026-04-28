import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from routers import (
    album_router,
    audio_edit_test_router,
    auth_router,
    auto_edit_router,
    chatbot_router,
    download_router,
    extend_router,
    image_to_song_router,
    inpaint_router,
    lyrics_router,
    mastering_router,
    music_router,
    payment_router,
    podcast_router,
    reference_match_router,
    project_router,
    prompt_router,
    queue_router,
    separation_router,
    sound_router,
    user_library_router,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from services.chatbot_indexer import build_index
    build_index()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title="AI Music Gen", version="1.0.0", routes=app.routes)
    schema.setdefault("components", {})["securitySchemes"] = {
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    }
    schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


app.include_router(auth_router.router)
app.include_router(project_router.router)
app.include_router(music_router.router)
app.include_router(inpaint_router.router)
app.include_router(lyrics_router.router)
app.include_router(separation_router.router)
app.include_router(download_router.router)
app.include_router(prompt_router.router)
app.include_router(extend_router.router)
app.include_router(album_router.router)
app.include_router(sound_router.router)
app.include_router(image_to_song_router.router)
app.include_router(queue_router.router)
app.include_router(audio_edit_test_router.router)
app.include_router(auto_edit_router.router)
app.include_router(mastering_router.router)
app.include_router(reference_match_router.router)
app.include_router(podcast_router.router)
app.include_router(payment_router.router)
app.include_router(user_library_router.router)
app.include_router(chatbot_router.router)


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI 🚀"}


@app.get("/health")
def health_check():
    logger.info("Health check called")
    return {"status": "ok"}


@app.get("/health/detailed")
def health_check_detailed():
    """
    Detailed health check for Phase 6 verification.
    Checks DB, Redis, and Celery worker connectivity. No auth required.
    """
    import os
    import redis as redis_lib
    from supabase_client import supabase
    from celery_app import celery_app

    result: dict = {"status": "ok", "checks": {}}

    # DB check
    try:
        supabase.table("users").select("id").limit(1).execute()
        result["checks"]["database"] = {"status": "ok"}
    except Exception as exc:
        result["checks"]["database"] = {"status": "error", "detail": str(exc)}
        result["status"] = "degraded"

    # Redis check
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        r = redis_lib.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        r.ping()
        result["checks"]["redis"] = {"status": "ok", "url": redis_url}
    except Exception as exc:
        result["checks"]["redis"] = {"status": "error", "detail": str(exc)}
        result["status"] = "degraded"

    # Celery worker check
    try:
        inspector = celery_app.control.inspect(timeout=2)
        pings = inspector.ping() or {}
        worker_count = len(pings)
        result["checks"]["celery"] = {
            "status": "ok" if worker_count > 0 else "no_workers",
            "worker_count": worker_count,
            "workers": list(pings.keys()),
        }
        if worker_count == 0:
            result["status"] = "degraded"
    except Exception as exc:
        result["checks"]["celery"] = {"status": "error", "detail": str(exc)}
        result["status"] = "degraded"

    return result
