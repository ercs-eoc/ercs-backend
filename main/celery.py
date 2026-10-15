import logging
import os
from logging.config import dictConfig

from banjo_utils.celery_health.worker import setup_worker_heartbeat
from celery import Celery, signals
from kombu import Queue

from main.cronjobs import BEAT_SCHEDULES

logger = logging.getLogger(__name__)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "main.settings")

app = Celery("main")
# banjo-utils worker heartbeat writer (read by banjo-celery-probe for k8s liveness).
setup_worker_heartbeat(app)

app.config_from_object("django.conf:settings", namespace="CELERY")


class CeleryQueue:
    # NOTE: Keep queue names lowercase (they are used in k8s resource names).
    default = Queue("default")
    report_llm = Queue("report-llm")

    ALL_QUEUE = (default, report_llm)


# Hard time limit of the longest task (only for document extraction).
LONGEST_TASK_SECONDS = 10 * 60 * 60 + 5 * 60

app.conf.task_default_queue = CeleryQueue.default.name
app.conf.task_queues = CeleryQueue.ALL_QUEUE
# Tasks not listed here go to the default queue.
app.conf.task_routes = {
    "apps.reports.tasks.task.handle_documents": {"queue": CeleryQueue.report_llm.name},
}
# NOTE: Redis re-delivers any message not acked within visibility_timeout (default 1h) to
# another worker. Keep it above the longest task so long LLM runs (and messages
# reserved behind them) aren't executed twice.
# https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html#visibility-timeout
app.conf.broker_transport_options = {
    "visibility_timeout": LONGEST_TASK_SECONDS + 60 * 60,
}
# Low concurrency + multi-hour tasks: don't reserve extra messages that would sit
# behind a long task while another worker is idle.
app.conf.worker_prefetch_multiplier = 1


app.conf.beat_schedule = BEAT_SCHEDULES

app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    logger.info("Request: %s", self.request)


@signals.setup_logging.connect
def config_loggers(**_):
    from django.conf import settings  # noqa: PLC0415

    dictConfig(settings.LOGGING)
