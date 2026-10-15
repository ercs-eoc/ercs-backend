import functools
import shlex
import subprocess
import typing
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import autoreload

WORKER_STATE_DIR = Path("/var/run/celery")

CMD = "celery -A main worker -E --concurrency=1 -l info -Q {queues}"


def restart_celery(queues: str) -> None:
    subprocess.call(shlex.split("pkill -9 celery"))
    subprocess.call(shlex.split(CMD.format(queues=queues)))


class Command(BaseCommand):
    """Start a Celery worker with Django's autoreloader so it restarts on code changes."""

    @typing.override
    def add_arguments(self, parser: typing.Any) -> None:
        parser.add_argument(
            "--queues",
            default="default,report-llm",
            help="Comma-separated celery queues to consume.",
        )

    @typing.override
    def handle(self, *args: typing.Any, **options: typing.Any) -> None:
        self.stdout.write(f"Starting celery worker ({options['queues']}) with autoreload...")
        WORKER_STATE_DIR.mkdir(parents=True, exist_ok=True)
        autoreload.run_with_reloader(functools.partial(restart_celery, options["queues"]))
