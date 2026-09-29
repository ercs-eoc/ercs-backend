import strawberry
import strawberry_django
from asgiref.sync import sync_to_async
from strawberry_django.pagination import OffsetPaginated

from main.graphql.context import Info
from main.graphql.permissions import IsAuthenticated

from .filters import UserFilter
from .orders import UserOrder
from .types import UserMeType, UserType


@strawberry.type
class Query:
    @strawberry.field
    @sync_to_async
    def me(self, info: Info) -> UserMeType | None:
        user = info.context.request.user
        if user.is_authenticated:
            return user  # type: ignore[reportGeneralTypeIssues]
        return None

    users: OffsetPaginated[UserType] = strawberry_django.offset_paginated(
        filters=UserFilter,
        ordering=UserOrder,
        permission_classes=[IsAuthenticated],
    )

    user: UserType = strawberry_django.field(permission_classes=[IsAuthenticated])
