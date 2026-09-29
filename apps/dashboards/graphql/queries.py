import strawberry
import strawberry_django
from strawberry_django.pagination import OffsetPaginated

from .filters import CapacityAndResourceFilter, ExternalDashboardFilter
from .orders import CapacityAndResourceOrder, ExternalDashboardOrder
from .types import CapacityAndResourceType, ExternalDashboardType


@strawberry.type
class Query:
    external_dashboards: OffsetPaginated[ExternalDashboardType] = strawberry_django.offset_paginated(
        filters=ExternalDashboardFilter,
        ordering=ExternalDashboardOrder,
    )

    external_dashboard: ExternalDashboardType = strawberry_django.field()

    capacity_and_resources: OffsetPaginated[CapacityAndResourceType] = strawberry_django.offset_paginated(
        filters=CapacityAndResourceFilter,
        ordering=CapacityAndResourceOrder,
    )

    capacity_and_resource: CapacityAndResourceType = strawberry_django.field()
