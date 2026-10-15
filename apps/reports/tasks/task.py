import logging
import traceback

from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.files.storage import default_storage
from django.utils import timezone

from apps.reports.ai_features.extraction import HeaderExtraction, PdfExtraction, PdfExtractionStats
from apps.reports.models import (
    DocumentExtraction,
    DocumentExtractionRun,
    DocumentExtractionStatus,
    Report,
    ReportContentType,
)

logger = logging.getLogger(__name__)

# Page-by-page LLM extraction + doc summary of long files can take hours on Ollama,
# far beyond the global CELERY_TASK_*_TIME_LIMIT.
DOCUMENT_EXTRACTION_SOFT_TIME_LIMIT = 10 * 60 * 60
DOCUMENT_EXTRACTION_TIME_LIMIT = DOCUMENT_EXTRACTION_SOFT_TIME_LIMIT + 5 * 60


def _embedding_model_name() -> str:
    if settings.LLM_USE_SENTENCE_TRANSFORMERS:
        return settings.SENTENCE_TRANSFORMER_MODEL_NAME or ""
    return settings.LLM_EMBEDDING_MODEL or ""


def _start_run(report: Report, run_id: str | None, celery_task_id: str | None) -> DocumentExtractionRun:
    # run_id is None for messages queued before runs were tracked.
    run = DocumentExtractionRun.objects.filter(pk=run_id).first() if run_id else None
    if run is None:
        run = DocumentExtractionRun(report=report)
    run.celery_task_id = celery_task_id or ""
    run.status = DocumentExtractionStatus.IN_PROGRESS
    run.started_at = timezone.now()
    run.llm_model = settings.LLM_MODEL_NAME or ""
    run.doc_summary_model = settings.LLM_DOC_SUMMARY_MODEL_NAME or ""
    run.embedding_model = _embedding_model_name()
    run.save()
    return run


def _finish_run(run: DocumentExtractionRun, stats: PdfExtractionStats | None) -> None:
    run.finished_at = timezone.now()
    if stats is not None:
        run.page_count = stats.page_count
        run.failed_page_count = stats.failed_page_count
        run.page_extraction_duration = stats.page_extraction_duration
        run.doc_summary_duration = stats.doc_summary_duration
        run.doc_summary_generated = stats.doc_summary_generated
    if run.status == DocumentExtractionStatus.IN_PROGRESS:
        partial = stats is not None and (stats.failed_page_count > 0 or not stats.doc_summary_generated)
        run.status = DocumentExtractionStatus.PARTIAL_SUCCESS if partial else DocumentExtractionStatus.SUCCESS
    run.save()


@shared_task(bind=True, soft_time_limit=DOCUMENT_EXTRACTION_SOFT_TIME_LIMIT, time_limit=DOCUMENT_EXTRACTION_TIME_LIMIT)
def handle_documents(
    self: Task,
    report_id: int,
    report_type: ReportContentType,
    run_id: str | None = None,
) -> None:
    report = Report.objects.filter(pk=report_id).first()

    if report is None:
        logger.warning("Report with id %s not found", report_id)
        return

    run = _start_run(report, run_id, self.request.id)
    stats: PdfExtractionStats | None = None

    try:
        if report_type == ReportContentType.FILE and report.file.name is None:
            logger.warning("Report with id %s has no file", report_id)
            run.status = DocumentExtractionStatus.FAILURE
            run.error_message = "Report has no file"
            return

        # Re-extraction (e.g. after a report edit/file replace) must start clean, otherwise
        # Any previous report entries will be delete and start fresh.
        DocumentExtraction.objects.filter(report=report).delete()

        if report.file and (file_name := report.file.name) and report_type == ReportContentType.FILE:
            with default_storage.open(file_name, "rb") as f:
                pdf_bytes = f.read()

            ext = PdfExtraction(
                report=report,
                data=pdf_bytes,
            )
            stats = ext.stats
            try:
                ext.pdf_to_images()
            except SoftTimeLimitExceeded:
                # Don't leave the doc summary stuck in PENDING when the task runs out of time.
                logger.error("Report with id %s: extraction exceeded the task time limit", report_id)
                DocumentExtraction.objects.filter(report=report, status=DocumentExtractionStatus.PENDING).update(
                    status=DocumentExtractionStatus.FAILURE,
                )
                raise
        elif report_type == ReportContentType.IFRAME:
            ext = HeaderExtraction(report=report)
            ext.handle_meta_info()
    except SoftTimeLimitExceeded:
        run.status = DocumentExtractionStatus.TIMED_OUT
        run.error_message = "Exceeded the task soft time limit"
        raise
    except Exception:
        run.status = DocumentExtractionStatus.FAILURE
        run.error_message = traceback.format_exc()
        raise
    finally:
        _finish_run(run, stats)
