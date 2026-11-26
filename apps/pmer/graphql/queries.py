import strawberry
import strawberry_django
from strawberry_django.pagination import OffsetPaginated

from .filters import PmerCategoryFilter, PmerDocumentTypeFilter, PmerReportFilter
from .orders import PmerReportOrder
from .types import PmerCategoryType, PmerDocumentTypeType, PmerReportType


@strawberry.type
class Query:
    pmer_categories: OffsetPaginated[PmerCategoryType] = strawberry_django.offset_paginated(
        filters=PmerCategoryFilter,
    )

    pmer_category: PmerCategoryType = strawberry_django.field()

    pmer_document_types: OffsetPaginated[PmerDocumentTypeType] = strawberry_django.offset_paginated(
        filters=PmerDocumentTypeFilter,
    )

    pmer_document_type: PmerDocumentTypeType = strawberry_django.field()

    pmer_reports: OffsetPaginated[PmerReportType] = strawberry_django.offset_paginated(
        filters=PmerReportFilter,
        ordering=PmerReportOrder,
    )

    pmer_report: PmerReportType = strawberry_django.field()
