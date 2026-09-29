import strawberry
import strawberry_django
from asgiref.sync import sync_to_async
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
    @sync_to_async
    def kobo_stats(self) -> KoboStats:
        return build_kobo_stats()

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
