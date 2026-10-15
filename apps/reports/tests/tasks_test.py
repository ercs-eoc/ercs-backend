import datetime
import typing
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync
from celery.exceptions import SoftTimeLimitExceeded
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.reports.ai_features.extraction import PdfExtractionStats
from apps.reports.extraction import trigger_document_extraction
from apps.reports.factories import FileReportFactory, ReportFactory
from apps.reports.models import DocumentExtractionRun, DocumentExtractionStatus, Report
from apps.reports.tasks.task import handle_documents
from main.tests import TestCase


def fake_pdf_extraction(stats: PdfExtractionStats, error: Exception | None = None) -> MagicMock:
    """Stand-in for PdfExtraction that reports `stats` (and optionally raises) without calling an LLM."""

    def build(**_: typing.Any) -> MagicMock:
        ext = MagicMock(stats=PdfExtractionStats())

        def pdf_to_images() -> None:
            ext.stats.__dict__.update(stats.__dict__)
            if error is not None:
                raise error

        ext.pdf_to_images.side_effect = pdf_to_images
        return ext

    return MagicMock(side_effect=build)


class TestHandleDocumentsRun(TestCase):
    file_report: Report

    @typing.override
    def setUp(self):
        super().setUp()
        self.file_report = FileReportFactory.create(
            file=SimpleUploadedFile("report.pdf", b"%PDF-1.4 fake", content_type="application/pdf"),
        )

    def run_file_task(self, pdf_extraction: MagicMock, run: DocumentExtractionRun | None = None) -> DocumentExtractionRun:
        with patch("apps.reports.tasks.task.PdfExtraction", pdf_extraction):
            handle_documents.apply(  # pyright: ignore[reportCallIssue]
                args=(self.file_report.pk, Report.ContentType.FILE, str(run.pk) if run else None),
                task_id="task-1",
            )
        return DocumentExtractionRun.objects.get(report=self.file_report)

    def test_trigger_queues_pending_run(self):
        with patch("apps.reports.extraction.handle_documents.apply_async") as mock_apply_async:
            async_to_sync(trigger_document_extraction)(
                self.file_report,
                trigger=DocumentExtractionRun.Trigger.REPORT_CREATED,
            )

        run = DocumentExtractionRun.objects.get(report=self.file_report)
        assert run.trigger == DocumentExtractionRun.Trigger.REPORT_CREATED
        assert run.status == DocumentExtractionStatus.PENDING
        assert run.started_at is None
        mock_apply_async.assert_called_once_with(
            args=(self.file_report.pk, self.file_report.content_type, str(run.pk)),
            task_id=run.celery_task_id,
        )

    def test_iframe_success_records_timings(self):
        report = ReportFactory.create()
        with patch("apps.reports.tasks.task.HeaderExtraction"):
            handle_documents.apply(args=(report.pk, Report.ContentType.IFRAME), task_id="task-iframe")  # pyright: ignore[reportCallIssue]

        run = DocumentExtractionRun.objects.get(report=report)
        assert run.status == DocumentExtractionStatus.SUCCESS
        assert run.celery_task_id == "task-iframe"
        assert run.started_at is not None
        assert run.finished_at is not None
        assert run.duration is not None
        assert run.page_count is None

    def test_updates_queued_run(self):
        run = DocumentExtractionRun.objects.create(
            report=self.file_report,
            trigger=DocumentExtractionRun.Trigger.REPORT_CREATED,
        )
        stats = PdfExtractionStats(
            page_count=3,
            page_extraction_duration=datetime.timedelta(minutes=5),
            doc_summary_duration=datetime.timedelta(minutes=1),
            doc_summary_generated=True,
        )
        updated = self.run_file_task(fake_pdf_extraction(stats), run=run)

        assert updated.pk == run.pk
        assert updated.status == DocumentExtractionStatus.SUCCESS
        assert updated.trigger == DocumentExtractionRun.Trigger.REPORT_CREATED
        assert updated.page_count == 3
        assert updated.failed_page_count == 0
        assert updated.page_extraction_duration == datetime.timedelta(minutes=5)
        assert updated.doc_summary_duration == datetime.timedelta(minutes=1)
        assert updated.queue_wait is not None

    def test_failed_pages_is_partial_success(self):
        stats = PdfExtractionStats(page_count=3, failed_page_count=1, doc_summary_generated=True)
        run = self.run_file_task(fake_pdf_extraction(stats))
        assert run.status == DocumentExtractionStatus.PARTIAL_SUCCESS

    def test_missing_doc_summary_is_partial_success(self):
        stats = PdfExtractionStats(page_count=3, doc_summary_generated=False)
        run = self.run_file_task(fake_pdf_extraction(stats))
        assert run.status == DocumentExtractionStatus.PARTIAL_SUCCESS
        assert run.doc_summary_generated is False

    def test_soft_time_limit_is_timed_out(self):
        stats = PdfExtractionStats(page_count=10, failed_page_count=2)
        run = self.run_file_task(fake_pdf_extraction(stats, error=SoftTimeLimitExceeded()))
        assert run.status == DocumentExtractionStatus.TIMED_OUT
        assert run.finished_at is not None
        # Progress up to the timeout is still recorded.
        assert run.page_count == 10
        assert run.failed_page_count == 2

    def test_exception_is_failure_with_traceback(self):
        run = self.run_file_task(fake_pdf_extraction(PdfExtractionStats(), error=RuntimeError("ollama down")))
        assert run.status == DocumentExtractionStatus.FAILURE
        assert "ollama down" in run.error_message
        assert run.finished_at is not None
