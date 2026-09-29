import strawberry
import strawberry_django
from strawberry_django.pagination import OffsetPaginated

from main.graphql.permissions import IsAuthenticated

from .filters import LinkFilter, ReportFilter, ReportSummaryFilter, ThematicAreaFilter
from .orders import LinkOrder
from .types import LinkType, ReportSummaryType, ReportType, ThematicAreaType


@strawberry.type
class Query:
    thematic_areas: OffsetPaginated[ThematicAreaType] = strawberry_django.offset_paginated(
        filters=ThematicAreaFilter,
    )

    reports: OffsetPaginated[ReportType] = strawberry_django.offset_paginated(
        filters=ReportFilter,
    )

    report: ReportType = strawberry_django.field()

    public_links: OffsetPaginated[LinkType] = strawberry_django.offset_paginated(
        filters=LinkFilter,
        ordering=LinkOrder,
    )

    internal_links: OffsetPaginated[LinkType] = strawberry_django.offset_paginated(
        filters=LinkFilter,
        ordering=LinkOrder,
        permission_classes=[IsAuthenticated],
    )

    link: LinkType = strawberry_django.field()

    report_summaries: OffsetPaginated[ReportSummaryType] = strawberry_django.offset_paginated(
        filters=ReportSummaryFilter,
        permission_classes=[IsAuthenticated],
    )

    report_summary: ReportSummaryType = strawberry_django.field()
