import strawberry
import strawberry_django
from django.db.models import Q

from apps.dashboards.models import CapacityAndResource, DashboardPage, ExternalDashboard
from apps.geo.models import AdminAreaLevel


@strawberry_django.filters.filter(ExternalDashboard, lookups=True)
class ExternalDashboardFilter:
    id: strawberry.ID | None = strawberry.UNSET
    page: DashboardPage | None = strawberry.UNSET
    is_active: bool | None = strawberry.UNSET
    show_on_home: bool | None = strawberry.UNSET
    region__level: AdminAreaLevel | None = strawberry.UNSET

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(title__icontains=value)

    @strawberry_django.filter_field
    def regions(self, queryset, value: list[strawberry.ID] | None, prefix: str) -> Q:
        if not value:
            return Q(region_id__isnull=True)
        return Q(region_id__in=value)

    @strawberry_django.filter_field
    def capacity_and_resources(self, queryset, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(capacity_and_resource_id__in=value)


@strawberry_django.filters.filter(CapacityAndResource, lookups=True)
class CapacityAndResourceFilter:
    id: strawberry.ID | None = strawberry.UNSET
    is_active: bool | None = strawberry.UNSET
    title: strawberry.auto

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(title__icontains=value) | Q(description__icontains=value)

    @strawberry_django.filter_field
    def regions(self, queryset, value: list[strawberry.ID] | None, prefix: str) -> Q:
        if not value:
            return Q(region_id__isnull=True)
        return Q(region_id__in=value)
