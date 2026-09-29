import strawberry
import strawberry_django
from strawberry_django.pagination import OffsetPaginated

from .filters import PmerReportFilter
from .orders import PmerReportOrder
from .types import PmerReportType


@strawberry.type
class Query:
    pmer_reports: OffsetPaginated[PmerReportType] = strawberry_django.offset_paginated(
        filters=PmerReportFilter,
        ordering=PmerReportOrder,
    )

    pmer_report: PmerReportType = strawberry_django.field()
