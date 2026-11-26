import strawberry
import strawberry_django
from django.db.models import Q

from apps.pmer.models import PmerCategory, PmerDocumentType, PmerReport
from apps.reports.models import ReportVisibility
from utils.file_types import FileTypeEnum, file_type_q


@strawberry_django.filters.filter(PmerCategory, lookups=True)
class PmerCategoryFilter:
    id: strawberry.ID | None = strawberry.UNSET
    name: str | None = strawberry.UNSET

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__icontains": value})


@strawberry_django.filters.filter(PmerDocumentType, lookups=True)
class PmerDocumentTypeFilter:
    id: strawberry.ID | None = strawberry.UNSET
    name: str | None = strawberry.UNSET

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__icontains": value})


@strawberry_django.filters.filter(PmerReport, lookups=True)
class PmerReportFilter:
    id: strawberry.ID | None = strawberry.UNSET
    category_id: strawberry.ID | None = strawberry.UNSET
    report_type_id: strawberry.ID | None = strawberry.UNSET
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
