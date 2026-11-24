import datetime

import strawberry
import strawberry_django
from asgiref.sync import sync_to_async
from graphql import GraphQLError
from strawberry_django.pagination import OffsetPaginated

from apps.kobo.stats import (
    build_emergency_detail,
    build_field_report_detail,
    build_kobo_stats,
    build_rapid_needs_detail,
)

from .filters import KoboSubmissionFilter
from .orders import KoboSubmissionOrder
from .types import (
    KoboEmergencyDetail,
    KoboEmergencyType,
    KoboFieldReportDetail,
    KoboRapidNeedsDetail,
    KoboStats,
    KoboSubmissionType,
)


@strawberry.type
class Query:
    @strawberry.field
    async def kobo_stats(
        self,
        start_date: datetime.date | None = None,
        end_date: datetime.date | None = None,
    ) -> KoboStats:
        # Inclusive submission-date range; omit both for the default last-6-months window.
        # A reversed range would otherwise match nothing and quietly return all-zero stats.
        if start_date is not None and end_date is not None and start_date > end_date:
            raise GraphQLError(
                "startDate must be on or before endDate.",
                extensions={"code": "INVALID_DATE_RANGE"},
            )
        return await sync_to_async(build_kobo_stats)(start_date=start_date, end_date=end_date)

    # Approved ERCS Emergency Alerts, shaped as an emergencies list (paginated).
    kobo_emergencies: OffsetPaginated[KoboEmergencyType] = strawberry_django.offset_paginated(
        ordering=KoboSubmissionOrder,
    )

    # Full detail for one alert (by submission id) + its linked RNA / field reports.
    @strawberry.field
    @sync_to_async
    def kobo_emergency(self, id: strawberry.ID) -> KoboEmergencyDetail | None:
        return build_emergency_detail(str(id))

    # Drill-down detail for a single Rapid Needs Assessment / Field Report.
    @strawberry.field
    @sync_to_async
    def kobo_rapid_needs(self, id: strawberry.ID) -> KoboRapidNeedsDetail | None:
        return build_rapid_needs_detail(str(id))

    @strawberry.field
    @sync_to_async
    def kobo_field_report(self, id: strawberry.ID) -> KoboFieldReportDetail | None:
        return build_field_report_detail(str(id))

    kobo_submissions: OffsetPaginated[KoboSubmissionType] = strawberry_django.offset_paginated(
        filters=KoboSubmissionFilter,
        ordering=KoboSubmissionOrder,
    )
    kobo_submission: KoboSubmissionType = strawberry_django.field()
