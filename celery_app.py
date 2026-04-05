"""
Celery application configuration.

One queue:
  musicgpt_album — handles ALL MusicGPT submissions (single-track + album tracks)
                   end-to-end (submit + poll).

Worker concurrency = MUSICGPT_MAX_PARALLEL (from .env, default 1).
This is the only number you change when upgrading your MusicGPT plan.
Each Celery worker slot = one request being submitted + polled at a time.
All requests queue up here, preventing 429 rate-limit errors from MusicGPT.
"""
import os
from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "ai_music_gen",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.music_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Task only acknowledged after it completes — safe if worker crashes mid-request.
    task_acks_late=True,
    worker_prefetch_multiplier=1,   # respect concurrency exactly, no pre-fetching
    task_routes={
        "tasks.music_tasks.submit_and_poll_task": {"queue": "musicgpt_album"},
        "tasks.music_tasks.process_album_track_task": {"queue": "musicgpt_album"},
    },
)
