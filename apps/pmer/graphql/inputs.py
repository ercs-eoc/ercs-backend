import strawberry
import strawberry_django
from strawberry.file_uploads import Upload

from apps.pmer.models import PmerReport
from apps.reports.models import ReportVisibility


@strawberry.input
class PmerCategoryInput:
    name: str


@strawberry.input
class PmerDocumentTypeInput:
    name: str


@strawberry_django.input(PmerReport)
class PmerReportCreateInput:
    title: strawberry.auto
    category: strawberry.ID
    report_type: strawberry.ID
    file: Upload
    description: strawberry.auto
    department: strawberry.auto
    project: strawberry.auto
    region: strawberry.ID | None = strawberry.UNSET
    visibility: ReportVisibility = ReportVisibility.PUBLIC


@strawberry_django.partial(PmerReport)
class PmerReportUpdateInput:
    title: strawberry.auto
    category: strawberry.ID | None = strawberry.UNSET
    report_type: strawberry.ID | None = strawberry.UNSET
    file: Upload | None = strawberry.UNSET
    description: strawberry.auto
    department: strawberry.auto
    project: strawberry.auto
    region: strawberry.ID | None = strawberry.UNSET
    visibility: ReportVisibility | None = strawberry.UNSET
