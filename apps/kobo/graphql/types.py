import datetime
from typing import Any

import strawberry
import strawberry_django

from apps.kobo.models import VALIDATION_STATUS_APPROVED, KoboForm, KoboHazard, KoboSubmission


def _raw_int(raw: dict[str, Any], key: str) -> int | None:
    try:
        return int(float(raw.get(key)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _humanize(value: str | None) -> str | None:
    """`South_Ethiopia` → `South Ethiopia` (Kobo uses underscores for spaces)."""
    return value.replace("_", " ").strip() if value else value


def raw_geolocation(raw: dict[str, Any]) -> tuple[float | None, float | None]:
    """Kobo's parsed `[lat, lon]`; returns (lat, lon) or (None, None)."""
    geo = raw.get("_geolocation") or []
    if len(geo) >= 2 and geo[0] is not None and geo[1] is not None:
        try:
            return float(geo[0]), float(geo[1])
        except (TypeError, ValueError):
            return None, None
    return None, None


def raw_zone(raw: dict[str, Any]) -> str | None:
    """Zone(s) — `zone-one` for woreda/kebele scope, `zone-multiple` for zone scope."""
    return _humanize(raw.get("geo/zone-one") or raw.get("geo/zone-multiple"))


def raw_woreda(raw: dict[str, Any]) -> str | None:
    return _humanize(raw.get("geo/woreda-one") or raw.get("geo/woreda-multiple"))


def raw_emergency_title(raw: dict[str, Any]) -> str:
    """Constructed heading: `<Disaster type> — <Zone/Woreda>, <Region>`.

    The Emergency Alert form has no title field, so we build one from the hazard
    and the most specific available locality.
    """
    hazard = (raw.get("context/hazard") or "").strip()
    hazard_disp = (hazard[:1].upper() + hazard[1:]) if hazard else "Emergency"
    region = _humanize(raw.get("geo/region-one"))
    locality = raw_zone(raw) or raw_woreda(raw)
    if locality and region and locality.casefold() != region.casefold():
        return f"{hazard_disp} — {locality}, {region}"
    if region:
        return f"{hazard_disp} — {region}"
    return hazard_disp


@strawberry_django.type(KoboSubmission)
class KoboSubmissionType:
    id: strawberry.ID
    form: int
    asset_uid: strawberry.auto
    kobo_id: strawberry.auto
    submission_time: strawberry.auto
    validation_status: strawberry.auto
    emergency_code: strawberry.auto
    region_id: strawberry.ID | None
    created_at: strawberry.auto
    updated_at: strawberry.auto

    @strawberry.field
    def form_display(self) -> str:
        return self.get_form_display()  # type: ignore[attr-defined]


@strawberry_django.type(
    KoboHazard,
    description="A hazard choice of the ERCS Kobo Emergency Alert form, with its GO disaster type match.",
)
class KoboHazardType:
    id: strawberry.ID
    code: strawberry.auto
    label: strawberry.auto
    go_disaster_type_id: strawberry.auto

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any, **kwargs: Any) -> Any:
        # Choices removed from the Kobo form are kept (for their GO mapping) but not offered.
        return queryset.filter(is_active=True).order_by("label")


@strawberry_django.type(KoboSubmission)
class KoboEmergencyType:
    """An ERCS Kobo Emergency Alert, shaped for the emergencies list.

    Scoped to approved Emergency Alert submissions (see get_queryset); the
    display fields are derived from the raw Kobo record.
    """

    id: strawberry.ID
    kobo_id: strawberry.auto
    submission_time: strawberry.auto
    emergency_code: strawberry.auto
    region_id: strawberry.ID | None

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any, **kwargs: Any) -> Any:
        return queryset.filter(
            form=KoboForm.EMERGENCY_ALERT,
            validation_status=VALIDATION_STATUS_APPROVED,
        )

    # `only=["raw"]` tells the optimizer to load the raw column, otherwise it is
    # deferred and `self.raw` triggers a lazy DB fetch in the async resolver.
    @strawberry_django.field(only=["raw"])
    def title(self) -> str:
        return raw_emergency_title(self.raw)  # type: ignore[attr-defined]

    @strawberry_django.field(only=["raw"])
    def hazard(self) -> str | None:
        return self.raw.get("context/hazard")  # type: ignore[attr-defined]

    @strawberry_django.field(only=["raw"])
    def latitude(self) -> float | None:
        return raw_geolocation(self.raw)[0]  # type: ignore[attr-defined]

    @strawberry_django.field(only=["raw"])
    def longitude(self) -> float | None:
        return raw_geolocation(self.raw)[1]  # type: ignore[attr-defined]

    @strawberry_django.field(only=["raw"])
    def alert_type(self) -> str | None:
        return self.raw.get("context/alert-type")  # type: ignore[attr-defined]

    @strawberry_django.field(only=["raw"])
    def region(self) -> str | None:
        return _humanize(self.raw.get("geo/region-one"))  # type: ignore[attr-defined]

    @strawberry_django.field(only=["raw"])
    def location_scope(self) -> str | None:
        return self.raw.get("geo/location_scope")  # type: ignore[attr-defined]

    @strawberry_django.field(only=["raw"])
    def start_date(self) -> str | None:
        return self.raw.get("context/start_date")  # type: ignore[attr-defined]

    @strawberry_django.field(only=["raw"])
    def people_affected(self) -> int | None:
        return _raw_int(self.raw, "ppl_impact_group/ppl_affected")  # type: ignore[attr-defined]

    @strawberry_django.field(only=["raw"])
    def people_displaced(self) -> int | None:
        return _raw_int(self.raw, "ppl_impact_group/ppl_affected_displaced")  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# Stats types (computed aggregates — not model-backed)
# --------------------------------------------------------------------------


@strawberry.type
class KeyCount:
    """A category and how many submissions fall in it (e.g. hazard → count)."""

    key: str
    count: int


@strawberry.type
class KoboSource:
    """Provenance + freshness for a single form's stats."""

    form: int
    form_label: str
    asset_uid: str
    last_fetched_at: datetime.datetime | None
    last_status: str
    total_records: int
    confirmed_records: int


@strawberry.type
class AlertStats:
    source: KoboSource
    total_emergencies: int
    people_affected: int
    people_displaced: int
    deaths: int
    injured: int
    missing: int
    by_hazard: list[KeyCount]
    by_region: list[KeyCount]


@strawberry.type
class RapidNeedsStats:
    source: KoboSource
    total_assessments: int
    people_in_need: int
    people_affected: int
    people_displaced: int
    top_priority_sectors: list[KeyCount]
    by_region: list[KeyCount]


@strawberry.type
class FieldStats:
    source: KoboSource
    total_reports: int
    people_reached: int
    staff_mobilized: int
    volunteers_mobilized: int
    bdrt_mobilized: int
    ambulances_mobilized: int
    support_requested: int
    by_region: list[KeyCount]


@strawberry.type
class KoboStats:
    """Key stats across the three confirmed EOC forms, each with its source
    (form + asset uid) and last-fetched date.
    """

    generated_at: datetime.datetime
    alert: AlertStats
    rapid_needs: RapidNeedsStats
    field: FieldStats


# --------------------------------------------------------------------------
# Emergency detail (alert + linked RNA / field reports) — for the alert popup
# --------------------------------------------------------------------------


@strawberry.type
class KoboRelatedReport:
    """A linked Rapid Needs Assessment or Field Report row, for the detail lists."""

    id: strawberry.ID
    kobo_id: int
    submission_time: datetime.datetime | None
    label: str
    # People in need (RNA) or people reached (Field Report).
    value: int | None


@strawberry.type
class KoboEmergencyDetail:
    """Full detail for a single Emergency Alert, joined with the Rapid Needs
    Assessments and Field Reports that share its emergency code. Backs the alert
    popup / detail modal (built in ``apps.kobo.stats.build_emergency_detail``).
    """

    id: strawberry.ID
    kobo_id: int
    emergency_code: str | None
    title: str
    hazard: str | None
    alert_type: str | None
    submission_time: datetime.datetime | None
    reporting_branch: str | None
    region: str | None
    zone: str | None
    woreda: str | None
    kebele: str | None
    location_scope: str | None
    onset_date: str | None
    general_description: str | None
    population_in_affected_area: int | None
    people_affected: int | None
    people_displaced: int | None
    latitude: float | None
    longitude: float | None
    rapid_needs: list[KoboRelatedReport]
    field_reports: list[KoboRelatedReport]


@strawberry.type
class KoboRapidNeedsDetail:
    """Full detail for one approved Rapid Needs Assessment (the RNA popup).

    Chip lists (affected groups, sectors, vulnerable groups, modalities) are
    label-resolved from the stored form schema (see ``apps.kobo.labels``).
    """

    id: strawberry.ID
    kobo_id: int
    emergency_code: str | None
    index: int
    title: str
    submission_time: datetime.datetime | None
    reporting_branch: str | None
    region: str | None
    zone: str | None
    woreda: str | None
    kebele: str | None
    people_in_need: int | None
    people_affected: int | None
    people_displaced: int | None
    people_affected_non_displaced: int | None
    top_affected_groups: list[str]
    priority_sectors: list[str]
    vulnerable_groups: list[str]
    response_modalities: list[str]


@strawberry.type
class KoboFieldReportDetail:
    """Full detail for one approved Emergency Field Report (the Field Report popup)."""

    id: strawberry.ID
    kobo_id: int
    emergency_code: str | None
    index: int
    title: str
    submission_time: datetime.datetime | None
    reporting_branch: str | None
    region: str | None
    location: str | None
    reporting_period_start: str | None
    reporting_period_end: str | None
    reporting_days: int | None
    people_reached: int | None
    volunteers: int | None
    staff: int | None
    bdrt: int | None
    type_of_reported_information: str | None
    prepositioned_stocks_used: str | None
    response_actions: list[str]
    latest_developments: str | None
