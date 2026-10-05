import typing

from django.core.exceptions import ValidationError
from django.db import models
from django_choices_field import IntegerChoicesField
from django_stubs_ext.db.models.manager import RelatedManager
from pgvector.django import HnswIndex, VectorField

from apps.common.models import BaseModel


class ReportContentType(models.IntegerChoices):
    """Determines how the report content is stored and rendered."""

    FILE = 10, "File"
    IFRAME = 20, "IFrame"


class ReportType(models.IntegerChoices):
    """Categorises the kind of report."""

    REPORT = 10, "Report"
    MANUAL = 20, "Manual"
    POLICY = 30, "Policy"
    GUIDELINE = 40, "Guideline"
    ONLINE_INTERACTIVE = 50, "Online Interactive"


class ReportVisibility(models.IntegerChoices):
    """Controls who can access the report."""

    PUBLIC = 10, "Public"
    PRIVATE = 20, "Private"


class DocumentExtractionStatus(models.IntegerChoices):
    """Lifecycle state of an AI document extraction job."""

    PENDING = 10, "Pending"
    IN_PROGRESS = 20, "In Progress"
    SUCCESS = 30, "Success"
    FAILURE = 40, "Failure"


class LinkType(models.IntegerChoices):
    """Distinguishes internal resources from external ones."""

    INTERNAL = 10, "Internal"
    EXTERNAL = 20, "External"


class ThematicArea(BaseModel):
    """Controlled vocabulary for report thematic areas."""

    name = models.CharField[str, str](max_length=255, unique=True)

    class Meta:  # type: ignore[reportIncompatibleVariableOverride]
        verbose_name = "Thematic Area"
        verbose_name_plural = "Thematic Areas"
        ordering = ["name"]

    @typing.override
    def __str__(self) -> str:
        return self.name


class Report(BaseModel):
    """Unified model for file-upload and iframe-embed reports.

    Visibility rules:
    - PUBLIC → PRIVATE is allowed (redact a report).
    - PRIVATE → PUBLIC is blocked at save() and must also be enforced at the API level.

    Content-type rules:
    - FILE: `file` field must be populated; `iframe_url` must be empty.
    - IFRAME: `iframe_url` must be populated; `file` must be empty.
    """

    ContentType = ReportContentType  # convenience alias
    Visibility = ReportVisibility  # convenience alias
    ReportType = ReportType  # convenience alias

    title = models.CharField[str, str](max_length=500)
    description = models.TextField[str | None, str | None](null=True, blank=True)
    cover_image = models.ImageField(upload_to="reports/covers/", null=True, blank=True)
    content_type: int = IntegerChoicesField(choices_enum=ReportContentType)  # type: ignore[reportAssignmentType]
    file = models.FileField(upload_to="reports/", null=True, blank=True)
    iframe_url = models.URLField[str | None, str | None](null=True, blank=True)
    visibility: int = IntegerChoicesField(choices_enum=ReportVisibility, default=ReportVisibility.PUBLIC)  # type: ignore[reportAssignmentType]
    report_type: int = IntegerChoicesField(choices_enum=ReportType, default=ReportType.REPORT)  # type: ignore[reportAssignmentType]
    thematic_area = models.ForeignKey(
        ThematicArea,
        on_delete=models.PROTECT,
        related_name="reports",
        blank=True,
        null=True,
    )
    region = models.ForeignKey(
        "geo.AdminArea",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports",
    )
    disaster_type = models.CharField[str | None, str | None](max_length=255, null=True, blank=True)
    owner = models.CharField[str | None, str | None](max_length=255, null=True, blank=True)
    uploaded_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="uploaded_reports",
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # reverse relation type hints
    newspost_reports: typing.ClassVar[RelatedManager["apps.content.models.NewsPostReport"]]  # type: ignore[name-defined]  # noqa: F821

    class Meta:  # type: ignore[reportIncompatibleVariableOverride]
        verbose_name = "Report"
        verbose_name_plural = "Reports"
        ordering = ["-created_at"]

    @typing.override
    def __str__(self) -> str:
        return self.title

    @typing.override
    def clean(self) -> None:
        if self.content_type == ReportContentType.FILE and not self.file:
            raise ValidationError({"file": "A file is required when content_type is FILE."})
        if self.content_type == ReportContentType.IFRAME and not self.iframe_url:
            raise ValidationError({"iframe_url": "An iframe URL is required when content_type is IFRAME."})

    @typing.override
    def save(self, *args, **kwargs) -> None:
        if self.pk:
            try:
                previous = Report.objects.get(pk=self.pk)
                if previous.visibility == ReportVisibility.PRIVATE and self.visibility == ReportVisibility.PUBLIC:
                    raise ValidationError(
                        "Cannot change visibility from PRIVATE to PUBLIC.",
                    )
            except Report.DoesNotExist:
                pass
        super().save(*args, **kwargs)


class DocumentExtraction(BaseModel):
    """Tracks the AI extraction lifecycle for a FILE-type Report.

    Created/reset whenever a REPORT-type report is created or its file replaced.
    The AI tool populates extracted_contents, search_text, summary, and status
    directly in the database once processing is complete.
    """

    Status = DocumentExtractionStatus  # convenience alias

    class ExtractionType(models.IntegerChoices):
        """Extraction Types."""

        EXTRACTED_CONTENT = 1, "Extracted Content"
        DOCUMENT_SUMMARY = 2, "Document Summary"
        PAGE_SUMMARY = 3, "Page Summary"
        KEYWORDS = 4, "Keywords"
        TABLE = 5, "Table"
        CHART = 6, "Chart"
        TITLE = 7, "Title"
        DESCRIPTION = 8, "Description"
        DOCUMENT_SUMMARY_SHORT = 9, "Document Summary Short"
        DOCUMENT_SUMMARY_SECTION = 10, "Document Summary Section"

    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name="document_extractions",
    )
    text = models.TextField[str, str](blank=True, default="")
    page_number = models.IntegerField(null=True, blank=True, db_index=True)
    chunk_type = IntegerChoicesField(choices_enum=ExtractionType, default=ExtractionType.DOCUMENT_SUMMARY)  # type: ignore[reportAssignmentType]
    embedding = VectorField(dimensions=768, null=True, blank=True)
    # Used only by DOCUMENT_SUMMARY_SECTION chunks: one row per document holding a
    # list of {"topic", "label", "content", "embedding"} entries (the doc's topical
    # summary sections, e.g. overview/impacts/etc, plus its short summary), each
    # independently embedded so a query can match a single topic without diluting
    # the signal across the whole document summary. `embedding` above stays null
    # for these rows since there is no single vector representing all of them.
    section_embeddings = models.JSONField(default=list, blank=True)
    status: int = IntegerChoicesField(choices_enum=DocumentExtractionStatus, default=DocumentExtractionStatus.PENDING)  # type: ignore[reportAssignmentType]

    class Meta:  # type: ignore[reportIncompatibleVariableOverride]
        verbose_name = "Document Extraction"
        verbose_name_plural = "Document Extractions"
        indexes = [
            HnswIndex(
                name="doc_embedding_hnsw_idx",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
                condition=models.Q(embedding__isnull=False),
            ),
        ]

    @typing.override
    def __str__(self) -> str:
        return f"Extraction for {self.report} ({self.get_status_display()})"  # type: ignore[reportAttributeAccessIssue]


class Link(BaseModel):
    """Internal or external resource links associated with reports."""

    LinkType = LinkType  # convenience alias

    title = models.CharField[str, str](max_length=500)
    description = models.TextField[str | None, str | None](null=True, blank=True)
    url = models.URLField[str, str](max_length=2000)
    link_type: int = IntegerChoicesField(choices_enum=LinkType)  # type: ignore[reportAssignmentType]

    class Meta:  # type: ignore[reportIncompatibleVariableOverride]
        verbose_name = "Link"
        verbose_name_plural = "Links"
        ordering = ["title"]

    @typing.override
    def __str__(self) -> str:
        return self.title
