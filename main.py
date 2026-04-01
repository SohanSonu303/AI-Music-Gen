import logging
from fastapi import FastAPI
from routers import (
    download_router,
    inpaint_router,
    lyrics_router,
    music_router,
    project_router,
    separation_router,
    sound_router,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()

app.include_router(project_router.router)
app.include_router(music_router.router)
app.include_router(inpaint_router.router)
app.include_router(lyrics_router.router)
app.include_router(separation_router.router)
app.include_router(download_router.router)
app.include_router(sound_router.router)

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI 🚀"}


@app.get("/health")
def health_check():
    logger.info("Health check called")
    return {"status": "ok"}
