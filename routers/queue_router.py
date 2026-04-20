import logging
import os

import redis
from fastapi import APIRouter, Depends

from auth.clerk_auth import get_current_user
from models.auth_model import UserContext
from celery_app import celery_app

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/queue", tags=["Queue"])


@router.get("/health")
def queue_health(user: UserContext = Depends(get_current_user)):
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    payload: dict = {
        "status": "degraded",
        "redis_url": redis_url,
        "redis_connected": False,
        "worker_count": 0,
        "workers": [],
        "active_queues": {},
    }

    try:
        redis_client = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        payload["redis_connected"] = bool(redis_client.ping())
    except Exception as exc:
        payload["redis_error"] = str(exc)
        logger.warning("Queue health: Redis check failed: %s", exc)

    try:
        inspector = celery_app.control.inspect(timeout=2)
        pings = inspector.ping() or {}
        payload["workers"] = list(pings.keys())
        payload["worker_count"] = len(payload["workers"])
        payload["active_queues"] = inspector.active_queues() or {}
    except Exception as exc:
        payload["celery_error"] = str(exc)
        logger.warning("Queue health: Celery inspect failed: %s", exc)

    if payload["redis_connected"] and payload["worker_count"] > 0:
        payload["status"] = "ok"
    return payload
