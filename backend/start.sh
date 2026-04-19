#!/bin/bash
set -e

# Start Celery worker in background
celery -A app.workers.celery_app worker --loglevel=info --concurrency=2 &

# Start FastAPI (foreground — container stays alive as long as this runs)
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
