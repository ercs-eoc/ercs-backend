import logging
import os
from logging.config import dictConfig

from banjo_utils.celery_health.worker import setup_worker_heartbeat
from celery import Celery, signals

from main.cronjobs import BEAT_SCHEDULES

logger = logging.getLogger(__name__)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "main.settings")

app = Celery("main")
# banjo-utils worker heartbeat writer (read by banjo-celery-probe for k8s liveness).
setup_worker_heartbeat(app)

app.config_from_object("django.conf:settings", namespace="CELERY")

app.conf.task_default_queue = "default"
# Document extraction runs for hours (page-by-page LLM calls), so it gets its own
# queue/worker instead of blocking every other task on the default queue.
app.conf.task_routes = {
    "apps.reports.tasks.task.handle_documents": {"queue": "report-llm"},
}

# Static beat schedule (no django-celery-beat); defined in main/cronjobs.py.
app.conf.beat_schedule = BEAT_SCHEDULES

app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    logger.info("Request: %s", self.request)


@signals.setup_logging.connect
def config_loggers(**_):
    from django.conf import settings  # noqa: PLC0415

    dictConfig(settings.LOGGING)
