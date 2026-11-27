import strawberry
import strawberry_django
from django.db.models import Q

from apps.teams.models import Team, TeamMember


@strawberry_django.filters.filter(Team, lookups=True)
class TeamFilter:
    id: strawberry.ID | None = strawberry.UNSET
    name: str | None = strawberry.UNSET
    created_at: strawberry.auto

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(name__icontains=value)


@strawberry_django.filters.filter(TeamMember, lookups=True)
class TeamMemberFilter:
    id: strawberry.ID | None = strawberry.UNSET
    team_id: strawberry.ID | None = strawberry.UNSET
    position: str | None = strawberry.UNSET

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(name__icontains=value)

    @strawberry_django.filter_field
    def regions(self, queryset, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(region_id__in=value)

    @strawberry_django.filter_field
    def woredas(self, queryset, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(woreda_id__in=value)
