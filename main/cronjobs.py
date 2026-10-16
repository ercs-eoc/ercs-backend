"""Celery beat (cronjob) definitions.

Single source of truth for all periodic tasks. ``main.celery`` reads
:data:`BEAT_SCHEDULES` from here, so registering a new cronjob is a matter of
adding one entry to :data:`SCHEDULES`.

All schedules are UTC (``settings.TIME_ZONE``); Ethiopia (EAT) is UTC+3.
"""

import typing

from celery.schedules import crontab


class TimeConstants:
    SECONDS_IN_A_MINUTE = 60
    SECONDS_IN_A_HOUR = 60 * 60
    SECONDS_IN_A_DAY = 24 * 60 * 60
    SECONDS_IN_A_WEEK = 7 * 24 * 60 * 60

    EVERY_WEEK = crontab(minute="1", hour="1", day_of_week="1")
    EVERY_DAY = crontab(minute="1", hour="1")
    EVERY_DAY_MIDNIGHT = crontab(minute="0", hour="0")  # 00:00 UTC


class CronJobOption(typing.TypedDict, total=False):
    """Subset of ``Task.apply_async`` options usable from a beat entry.

    https://docs.celeryq.dev/en/latest/reference/celery.app.task.html#celery.app.task.Task.apply_async
    """

    expires: float
    """Seconds after dispatch when the task expires. An expired task is
    discarded instead of executed -- keeps a backed-up queue from running a
    stale copy of a job that has already been scheduled again."""

    time_limit: int
    soft_time_limit: int
    queue: str


class CeleryBeatSchedule(typing.TypedDict):
    task: str
    schedule: crontab
    options: CronJobOption
    args: tuple[typing.Any, ...] | None


class CronJob(typing.NamedTuple):
    task: str
    """Registered celery task name, eg. ``apps.kobo.tasks.sync_kobo``."""

    schedule: crontab
    args: tuple[typing.Any, ...] | None = None
    options: CronJobOption = {}  # noqa: RUF012


SCHEDULES: dict[str, CronJob] = {
    "sync_kobo": CronJob(
        task="apps.kobo.tasks.sync_kobo",
        schedule=TimeConstants.EVERY_WEEK,
        options=CronJobOption(expires=2 * TimeConstants.SECONDS_IN_A_DAY),
    ),
}


BEAT_SCHEDULES: dict[str, CeleryBeatSchedule] = {
    name: {
        "task": config.task,
        "args": config.args,
        "schedule": config.schedule,
        "options": config.options,
    }
    for name, config in SCHEDULES.items()
}
