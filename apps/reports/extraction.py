"""AI document extraction trigger for REPORT-type reports."""

import logging
import uuid

from apps.reports.models import DocumentExtractionRun, Report, ReportContentType
from apps.reports.tasks.task import handle_documents

logger = logging.getLogger(__name__)


async def trigger_document_extraction(
    report: Report,
    trigger: DocumentExtractionRun.Trigger,
) -> None:
    """Record a queued DocumentExtractionRun and dispatch the extraction task.

    Called after a REPORT-type report is created or its file is replaced.
    The task updates the run (timings, status, errors) as it executes.
    """
    if report.content_type == ReportContentType.FILE and not report.file.name:
        logger.warning("Report file is missing")
        return

    logger.info(
        "Triggering document extraction for report_id=%s",
        str(report.pk),
    )
    task_id = str(uuid.uuid4())
    run = await DocumentExtractionRun.objects.acreate(
        report=report,
        trigger=trigger,
        celery_task_id=task_id,
    )
    handle_documents.apply_async(  # pyright: ignore[reportCallIssue]
        args=(report.pk, report.content_type, str(run.pk)),
        task_id=task_id,
    )
