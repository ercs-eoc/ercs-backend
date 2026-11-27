import datetime
from collections.abc import Iterable

import strawberry
import strawberry_django
from django.db.models import Exists, OuterRef, Q, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Replace, Upper

from apps.geo.models import AdminArea
from apps.kobo.models import KoboSubmission


@strawberry_django.filters.filter(KoboSubmission, lookups=True)
class KoboSubmissionFilter:
    id: strawberry.ID | None = strawberry.UNSET
    form: int | None = strawberry.UNSET
    validation_status: str | None = strawberry.UNSET
    emergency_code: str | None = strawberry.UNSET

    @strawberry_django.filter_field
    def regions(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(region_id__in=value)


def _raw_region_name_q(names: Iterable[str], prefix: str) -> Q:
    """Match `raw["geo/region-one"]` against region names.

    Kobo stores underscores for spaces ("South_Ethiopia"), so both spellings are
    matched, case-insensitively. No names → matches nothing.
    """
    q = Q()
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        for variant in {name, name.replace(" ", "_")}:
            q |= Q(**{f"{prefix}raw__geo/region-one__iexact": variant})
    return q or Q(pk__in=[])


@strawberry_django.filters.filter(KoboSubmission)
class KoboEmergencyFilter:
    @strawberry_django.filter_field
    def regions(self, value: list[strawberry.ID], prefix: str) -> Q:
        raw_region = Upper(KeyTextTransform("geo/region-one", OuterRef(f"{prefix}raw")))
        name_matches = (
            AdminArea.objects.filter(id__in=value)
            .alias(
                name_upper=Upper("name"),
                name_underscored=Upper(Replace("name", Value(" "), Value("_"))),
            )
            .filter(Q(name_upper=raw_region) | Q(name_underscored=raw_region))
        )
        return Q(**{f"{prefix}region_id__in": value}) | Q(Exists(name_matches))

    @strawberry_django.filter_field
    def region_names(self, value: list[str], prefix: str) -> Q:
        # Region names as returned by `KoboEmergencyType.region` (e.g. "South Ethiopia").
        return _raw_region_name_q(value, prefix)

    @strawberry_django.filter_field
    def hazards(self, value: list[str], prefix: str) -> Q:
        return Q(**{f"{prefix}raw__context/hazard__in": value})

    @strawberry_django.filter_field
    def start_date_gte(self, value: datetime.date, prefix: str) -> Q:
        return Q(**{f"{prefix}raw__context/start_date__gte": value.isoformat()})

    @strawberry_django.filter_field
    def start_date_lte(self, value: datetime.date, prefix: str) -> Q:
        return Q(**{f"{prefix}raw__context/start_date__lte": value.isoformat()})
