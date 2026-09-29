import strawberry
import strawberry_django
from strawberry_django.pagination import OffsetPaginated

from .filters import AdminAreaFilter
from .orders import AdminAreaOrder
from .types import AdminAreaType


@strawberry.type
class Query:
    admin_areas: OffsetPaginated[AdminAreaType] = strawberry_django.offset_paginated(
        filters=AdminAreaFilter,
        ordering=AdminAreaOrder,
    )

    admin_area: AdminAreaType = strawberry_django.field()
