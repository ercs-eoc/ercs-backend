import strawberry
import strawberry_django
from django.contrib.staticfiles.storage import staticfiles_storage
from strawberry_django.pagination import OffsetPaginated

from main.graphql.permissions import IsAuthenticated

from .filters import TeamFilter, TeamMemberFilter
from .orders import TeamMemberOrder, TeamOrder
from .types import TeamMemberType, TeamType


@strawberry.type
class Query:
    teams: OffsetPaginated[TeamType] = strawberry_django.offset_paginated(
        filters=TeamFilter,
        ordering=TeamOrder,
        permission_classes=[IsAuthenticated],
    )

    team: TeamType = strawberry_django.field(
        permission_classes=[IsAuthenticated],
    )

    team_members: OffsetPaginated[TeamMemberType] = strawberry_django.offset_paginated(
        filters=TeamMemberFilter,
        ordering=TeamMemberOrder,
        permission_classes=[IsAuthenticated],
    )

    team_member: TeamMemberType = strawberry_django.field(
        permission_classes=[IsAuthenticated],
    )

    @strawberry.field(permission_classes=[IsAuthenticated])
    def create_team_member_template(self, info: strawberry.Info) -> str:
        request = info.context.request

        return request.build_absolute_uri(
            staticfiles_storage.url("files/create-team-member-template.xlsx"),
        )
