from datetime import datetime, timezone
from typing import Optional

_mock_task_registry: dict[str, datetime] = {}

MOCK_COMPLETE_AFTER_SECONDS = 40


def register_mock_task(task_id: str) -> None:
    _mock_task_registry[task_id] = datetime.now(timezone.utc)


def get_mock_elapsed(task_id: str) -> Optional[float]:
    registered_at = _mock_task_registry.get(task_id)
    if registered_at is None:
        return None
    return (datetime.now(timezone.utc) - registered_at).total_seconds()


def is_mock_completed(task_id: str) -> bool:
    elapsed = get_mock_elapsed(task_id)
    if elapsed is None:
        return True  # unknown task_id → return completed gracefully
    return elapsed >= MOCK_COMPLETE_AFTER_SECONDS
