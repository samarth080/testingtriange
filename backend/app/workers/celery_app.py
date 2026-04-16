"""
Celery application instance.

Tasks are registered in separate modules (ingestion.tasks, triage.tasks)
and autodiscovered here. The broker is Redis; results are also stored in Redis.

Worker concurrency and task routing are configured here. Day 2 will add
actual task definitions for backfill and indexing.
"""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "triage_copilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.ingestion_tasks",  # Day 2: backfill_repo task
        "app.workers.indexing_tasks",   # Day 3: index_repo task
        "app.workers.triage_tasks",     # Day 5: triage_issue task
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Prevent tasks from silently disappearing if a worker dies mid-task
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
