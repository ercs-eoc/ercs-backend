import strawberry
import strawberry_django
from strawberry_django.pagination import OffsetPaginated

from .filters import EmergencyFilter
from .orders import EmergencyOrder
from .types import EmergencyType


@strawberry.type
class Query:
    emergencies: OffsetPaginated[EmergencyType] = strawberry_django.offset_paginated(
        filters=EmergencyFilter,
        ordering=EmergencyOrder,
    )

    emergency: EmergencyType = strawberry_django.field()
