import typing

from django.db import models
from django_choices_field import IntegerChoicesField

from apps.common.models import BaseModel
from apps.reports.models import ReportVisibility


class PmerCategory(BaseModel):
    """User-managed thematic category a PMER report belongs to."""

    name = models.CharField[str, str](max_length=255, unique=True)

    class Meta:  # type: ignore[reportIncompatibleVariableOverride]
        verbose_name = "PMER Category"
        verbose_name_plural = "PMER Categories"

    @typing.override
    def __str__(self) -> str:
        return self.name


class PmerDocumentType(BaseModel):
    """User-managed kind of PMER document (e.g. Strategic Plan, Annual Report)."""

    name = models.CharField[str, str](max_length=255, unique=True)

    class Meta:  # type: ignore[reportIncompatibleVariableOverride]
        verbose_name = "PMER Document Type"
        verbose_name_plural = "PMER Document Types"

    @typing.override
    def __str__(self) -> str:
        return self.name


class PmerReport(BaseModel):
    """Planning, Monitoring, Evaluation and Reporting (PMER) document."""

    Visibility = ReportVisibility  # convenience alias

    title = models.CharField[str, str](max_length=500)
    description = models.TextField[str | None, str | None](null=True, blank=True)
    file = models.FileField(upload_to="pmer/")
    category = models.ForeignKey(
        PmerCategory,
        on_delete=models.PROTECT,
        related_name="pmer_reports",
    )
    report_type = models.ForeignKey(
        PmerDocumentType,
        on_delete=models.PROTECT,
        related_name="pmer_reports",
    )
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="created_pmer_reports",
    )
    region = models.ForeignKey(
        "geo.AdminArea",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pmer_region",
    )
    department = models.CharField[str | None, str | None](max_length=250, null=True, blank=True)
    project = models.CharField[str | None, str | None](max_length=250, null=True, blank=True)
    visibility: int = IntegerChoicesField(choices_enum=ReportVisibility, default=ReportVisibility.PUBLIC)  # type: ignore[reportAssignmentType]

    class Meta:  # type: ignore[reportIncompatibleVariableOverride]
        verbose_name = "PMER Report"
        verbose_name_plural = "PMER Reports"
        ordering = ["-created_at"]

    @typing.override
    def __str__(self) -> str:
        return self.title
