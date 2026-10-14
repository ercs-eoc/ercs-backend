"""AI document extraction trigger for REPORT-type reports."""

import logging

from apps.reports.models import Report, ReportContentType
from apps.reports.tasks.task import handle_documents

logger = logging.getLogger(__name__)


async def trigger_document_extraction(report: Report) -> None:
    """Create or reset the DocumentExtraction record and dispatch to the AI tool.

    Called after a REPORT-type report is created or its file is replaced.
    The AI tool is expected to update extracted_contents, search_text, summary,
    and status directly in the database once processing completes.
    """
    if report.content_type == ReportContentType.FILE and not report.file.name:
        logger.warning("Report file is missing")
        return

    logger.info(
        "Triggering document extraction for report_id=%s",
        str(report.pk),
    )
    handle_documents.apply_async(args=(report.pk, report.content_type))  # pyright: ignore[reportCallIssue]
