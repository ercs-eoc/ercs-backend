import strawberry
import strawberry_django
from django.db.models import Q

from apps.pmer.models import PmerReport, PmerReportCategory, PmerReportDocumentType
from apps.reports.models import ReportVisibility
from utils.file_types import FileTypeEnum, file_type_q


@strawberry_django.filters.filter(PmerReport, lookups=True)
class PmerReportFilter:
    id: strawberry.ID | None = strawberry.UNSET
    category: PmerReportCategory | None = strawberry.UNSET
    report_type: PmerReportDocumentType | None = strawberry.UNSET
    title: strawberry.auto
    department: strawberry.auto
    project: strawberry.auto
    region_id: strawberry.ID | None = strawberry.UNSET
    visibility: ReportVisibility | None = strawberry.UNSET

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(title__icontains=value) | Q(project__icontains=value) | Q(department__icontains=value)

    @strawberry_django.filter_field
    def file_types(self, value: list[FileTypeEnum], prefix: str) -> Q:
        return file_type_q(f"{prefix}file", value)
