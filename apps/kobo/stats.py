"""Compute the key dashboard stats from stored (confirmed) Kobo submissions.

Numbers live as strings inside ``raw`` (Kobo exports everything as text), so
aggregation happens in Python. Volumes are small (hundreds of rows/form), so a
single pass per form is more than fast enough. Only submissions whose
``validation_status`` is approved are counted.

Region breakdowns use the ``AdminArea`` matched during sync (a clean canonical
name like "Oromia"); if a submission's region did not match, we fall back to a
humanized version of the raw Kobo region string (e.g. ``South_Ethiopia`` →
``South Ethiopia``).
"""

import datetime
from collections import Counter
from typing import Any, NamedTuple

import strawberry
from django.utils import timezone

from apps.kobo.graphql.types import (
    AlertStats,
    FieldStats,
    KeyCount,
    KoboEmergencyDetail,
    KoboFieldReportDetail,
    KoboRapidNeedsDetail,
    KoboRelatedReport,
    KoboSource,
    KoboStats,
    RapidNeedsStats,
    raw_emergency_title,
    raw_geolocation,
    raw_woreda,
    raw_zone,
)
from apps.kobo.labels import FormLabels
from apps.kobo.models import VALIDATION_STATUS_APPROVED, KoboForm, KoboSubmission, KoboSyncState

# Headline stats show recent activity only: submissions from the last ~6 months
# (by Kobo submission time). A calendar-exact boundary is unnecessary for a
# dashboard window, so a fixed 180-day lookback keeps it dependency-free.
# Used only when the caller gives no explicit date range.
STATS_WINDOW = datetime.timedelta(days=180)


class DateRange(NamedTuple):
    """Inclusive submission-date bounds; either side may be open (``None``)."""

    start: datetime.date | None = None
    end: datetime.date | None = None

    @property
    def is_set(self) -> bool:
        return self.start is not None or self.end is not None


class Row(NamedTuple):
    """A confirmed submission, as loaded for aggregation."""

    raw: dict[str, Any]
    region_name: str | None
    emergency_code: str | None
    kobo_id: int


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _humanize(value: str | None) -> str | None:
    return value.replace("_", " ").strip() if value else value


def _sum(rows: list[Row], key: str) -> int:
    return sum(_to_int(row.raw.get(key)) for row in rows)


def _breakdown(rows: list[Row], key: str) -> list[KeyCount]:
    counter = Counter(str(row.raw.get(key)) for row in rows if row.raw.get(key))
    return [KeyCount(key=k, count=n) for k, n in counter.most_common()]


def _region_breakdown(rows: list[Row], raw_key: str) -> list[KeyCount]:
    """Count by matched AdminArea name, falling back to the humanized raw name."""
    counter: Counter[str] = Counter()
    for row in rows:
        name = row.region_name or _humanize(str(row.raw.get(raw_key) or "")) or "Unknown"
        counter[name] += 1
    return [KeyCount(key=k, count=n) for k, n in counter.most_common()]


def _source(form: KoboForm, confirmed: int) -> KoboSource:
    state = KoboSyncState.objects.filter(form=form).first()
    return KoboSource(
        form=int(form),
        form_label=str(KoboForm(form).label),
        asset_uid=state.asset_uid if state else "",
        last_fetched_at=state.last_fetched_at if state else None,
        last_status=state.last_status if state else "",
        total_records=state.record_count if state else 0,
        confirmed_records=confirmed,
    )


def _confirmed(form: KoboForm, date_range: DateRange) -> list[Row]:
    """Approved submissions for a form, limited by submission date.

    With an explicit ``date_range`` its (inclusive, possibly open-ended) bounds
    apply; otherwise the default ``STATS_WINDOW`` lookback does.
    """
    qs = KoboSubmission.objects.filter(
        form=form,
        validation_status=VALIDATION_STATUS_APPROVED,
    )
    if date_range.is_set:
        if date_range.start is not None:
            qs = qs.filter(submission_time__date__gte=date_range.start)
        if date_range.end is not None:
            qs = qs.filter(submission_time__date__lte=date_range.end)
    else:
        qs = qs.filter(submission_time__gte=timezone.now() - STATS_WINDOW)
    return [Row(*values) for values in qs.values_list("raw", "region__name", "emergency_code", "kobo_id")]


def _alert_stats(date_range: DateRange) -> AlertStats:
    rows = _confirmed(KoboForm.EMERGENCY_ALERT, date_range)
    # The promoted column, derived once during sync from `FORM_SPECS`.
    codes = {row.emergency_code for row in rows if row.emergency_code}
    return AlertStats(
        source=_source(KoboForm.EMERGENCY_ALERT, len(rows)),
        total_emergencies=len(codes),
        people_affected=_sum(rows, "ppl_impact_group/ppl_affected"),
        people_displaced=_sum(rows, "ppl_impact_group/ppl_affected_displaced"),
        deaths=_sum(rows, "ppl_impact_group/ppl_dead"),
        injured=_sum(rows, "ppl_impact_group/ppl_wounded"),
        missing=_sum(rows, "ppl_impact_group/ppl_missing"),
        by_hazard=_breakdown(rows, "context/hazard"),
        by_region=_region_breakdown(rows, "geo/region-one"),
    )


def _rapid_needs_stats(date_range: DateRange) -> RapidNeedsStats:
    rows = _confirmed(KoboForm.RAPID_NEEDS_ASSESSMENT, date_range)
    return RapidNeedsStats(
        source=_source(KoboForm.RAPID_NEEDS_ASSESSMENT, len(rows)),
        total_assessments=len(rows),
        people_in_need=_sum(rows, "ppl_impact_group/ppl_in_need"),
        people_affected=_sum(rows, "ppl_impact_group/ppl_affected"),
        people_displaced=_sum(rows, "ppl_impact_group/ppl_affected_displaced"),
        top_priority_sectors=_breakdown(rows, "priority_sectors/sector1"),
        by_region=_region_breakdown(rows, "location/region"),
    )


def _branch_key(row: Row) -> tuple[Any, Any]:
    """The ``(emergency, branch)`` bucket a Field sitrep belongs to.

    A row with neither key becomes its own bucket, keyed on ``kobo_id`` —
    collapsing every unkeyed row into one shared bucket would let
    :func:`_max_per_branch` discard all but the largest of them.
    """
    branch = row.raw.get("context/reporting_branch")
    if not row.emergency_code and not branch:
        return ("kobo_id", row.kobo_id)
    return (row.emergency_code, branch)


def _max_per_branch(rows: list[Row], key: str) -> int:
    """Sum ``key``'s peak value per ``(emergency, branch)``.

    Field figures are restated in every periodic sitrep, so a plain sum
    multiplies a branch's contribution by how often it reported. We take that
    branch's peak for the emergency as the proxy for its response, then sum
    across branches and emergencies.
    """
    peaks: dict[tuple[Any, Any], int] = {}
    for row in rows:
        bucket = _branch_key(row)
        peaks[bucket] = max(peaks.get(bucket, 0), _to_int(row.raw.get(key)))
    return sum(peaks.values())


def _support_requested(rows: list[Row]) -> int:
    """Branch responses that requested support at least once.

    ``support_required`` is a ``select_multiple``: a space-delimited list of what
    the branch needs, absent/empty when nothing was requested. Counted per
    ``(emergency, branch)`` like the other Field figures, so a branch repeating
    the request in each sitrep still counts once.
    """
    return len({_branch_key(row) for row in rows if row.raw.get("branch_sitrep/resources_group/support_required")})


def _field_stats(date_range: DateRange) -> FieldStats:
    rows = _confirmed(KoboForm.EMERGENCY_FIELD, date_range)
    return FieldStats(
        source=_source(KoboForm.EMERGENCY_FIELD, len(rows)),
        total_reports=len(rows),
        # Summed across all field reports: each report is a distinct reporting
        # period / response action, so different reports are not assumed to reach
        # the same people. (Resource figures below stay deduped per branch, since
        # e.g. the same staff are restated in every periodic sitrep.)
        people_reached=_sum(rows, "branch_sitrep/reached_population/g_reach"),
        staff_mobilized=_max_per_branch(rows, "branch_sitrep/resources_group/resources_staff"),
        volunteers_mobilized=_max_per_branch(rows, "branch_sitrep/resources_group/resources_volunteers"),
        bdrt_mobilized=_max_per_branch(rows, "branch_sitrep/resources_group/resources_BDRT"),
        ambulances_mobilized=_max_per_branch(rows, "branch_sitrep/resources_group/resources_ambulances"),
        support_requested=_support_requested(rows),
        by_region=_region_breakdown(rows, "location/region-one"),
    )


def build_kobo_stats(
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> KoboStats:
    """Headline stats for submissions in ``[start_date, end_date]`` (by submission date).

    Without either bound, falls back to the last ``STATS_WINDOW`` (~6 months).
    """
    date_range = DateRange(start=start_date, end=end_date)
    return KoboStats(
        generated_at=timezone.now(),
        alert=_alert_stats(date_range),
        rapid_needs=_rapid_needs_stats(date_range),
        field=_field_stats(date_range),
    )


# --------------------------------------------------------------------------
# Emergency detail (alert + linked RNA / field reports)
# --------------------------------------------------------------------------


def _to_int_or_none(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first_humanized(raw: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = raw.get(key)
        if value:
            return _humanize(str(value))
    return None


def _related_reports(
    form: KoboForm,
    code: str,
    prefix: str,
    value_key: str,
    locality_keys: tuple[str, ...],
) -> list[KoboRelatedReport]:
    """Approved submissions of ``form`` sharing this emergency ``code``, numbered
    in submission order (``#1``, ``#2``, …) and labelled for the detail lists.

    Not windowed to 6 months: the popup lists every report tied to the emergency.
    """
    reports: list[KoboRelatedReport] = []
    rows = KoboSubmission.objects.filter(
        form=form,
        emergency_code=code,
        validation_status=VALIDATION_STATUS_APPROVED,
    ).order_by("submission_time", "kobo_id")
    for index, sub in enumerate(rows, start=1):
        label = f"{code} — {prefix} #{index}"
        locality = _first_humanized(sub.raw, locality_keys)
        if locality:
            label += f" ({locality})"
        reports.append(
            KoboRelatedReport(
                id=strawberry.ID(str(sub.id)),
                kobo_id=sub.kobo_id,
                submission_time=sub.submission_time,
                label=label,
                value=_to_int_or_none(sub.raw.get(value_key)),
            ),
        )
    return reports


def build_emergency_detail(submission_id: str) -> KoboEmergencyDetail | None:
    """Full detail for one approved Emergency Alert (by submission id), joined
    with the RNA and Field reports that share its emergency code.
    """
    alert = KoboSubmission.objects.filter(
        id=submission_id,
        form=KoboForm.EMERGENCY_ALERT,
        validation_status=VALIDATION_STATUS_APPROVED,
    ).first()
    if alert is None:
        return None

    raw = alert.raw
    code = alert.emergency_code
    lat, lon = raw_geolocation(raw)
    region = _humanize(raw.get("geo/region-one"))

    return KoboEmergencyDetail(
        id=strawberry.ID(str(alert.id)),
        kobo_id=alert.kobo_id,
        emergency_code=code,
        title=raw_emergency_title(raw),
        hazard=raw.get("context/hazard"),
        alert_type=raw.get("context/alert-type"),
        submission_time=alert.submission_time,
        # The alert form carries only a branch code; the region name is what the
        # design shows as the reporting branch (e.g. "Somali branch").
        reporting_branch=region,
        region=region,
        zone=raw_zone(raw),
        woreda=raw_woreda(raw),
        kebele=_humanize(raw.get("geo/kebele")),
        location_scope=raw.get("geo/location_scope"),
        onset_date=raw.get("context/start_date"),
        general_description=raw.get("context/general_description"),
        population_in_affected_area=_to_int_or_none(raw.get("ppl_impact_group/ppl_before")),
        people_affected=_to_int_or_none(raw.get("ppl_impact_group/ppl_affected")),
        people_displaced=_to_int_or_none(raw.get("ppl_impact_group/ppl_affected_displaced")),
        latitude=lat,
        longitude=lon,
        rapid_needs=_related_reports(
            KoboForm.RAPID_NEEDS_ASSESSMENT,
            code,
            "RNA",
            "ppl_impact_group/ppl_in_need",
            ("location/woreda", "location/zone"),
        )
        if code
        else [],
        field_reports=_related_reports(
            KoboForm.EMERGENCY_FIELD,
            code,
            "Field Report",
            "branch_sitrep/reached_population/g_reach",
            (),
        )
        if code
        else [],
    )


# --------------------------------------------------------------------------
# RNA / Field Report detail (the drill-down popups)
# --------------------------------------------------------------------------


def _report_index(sub: KoboSubmission) -> int:
    """1-based position of ``sub`` among its approved same-emergency siblings.

    Matches the ``#1``/``#2`` numbering used in the emergency detail's linked lists.
    """
    if not sub.emergency_code:
        return 1
    sibling_ids = list(
        KoboSubmission.objects.filter(
            form=sub.form,
            emergency_code=sub.emergency_code,
            validation_status=VALIDATION_STATUS_APPROVED,
        )
        .order_by("submission_time", "kobo_id")
        .values_list("id", flat=True),
    )
    try:
        return sibling_ids.index(sub.id) + 1
    except ValueError:
        return 1


def _alert_region(code: str | None) -> str | None:
    """Region name of the parent Emergency Alert for ``code`` (the Field branch proxy)."""
    if not code:
        return None
    alert = KoboSubmission.objects.filter(
        form=KoboForm.EMERGENCY_ALERT,
        emergency_code=code,
        validation_status=VALIDATION_STATUS_APPROVED,
    ).first()
    return _humanize(alert.raw.get("geo/region-one")) if alert else None


def build_rapid_needs_detail(submission_id: str) -> KoboRapidNeedsDetail | None:
    """Full detail for one approved Rapid Needs Assessment, with resolved chip labels."""
    sub = KoboSubmission.objects.filter(
        id=submission_id,
        form=KoboForm.RAPID_NEEDS_ASSESSMENT,
        validation_status=VALIDATION_STATUS_APPROVED,
    ).first()
    if sub is None:
        return None

    raw = sub.raw
    labels = FormLabels.load(KoboForm.RAPID_NEEDS_ASSESSMENT)
    code = sub.emergency_code
    index = _report_index(sub)
    woreda = labels.resolve_one("location/woreda", raw.get("location/woreda"))
    title = f"{code} — RNA #{index}" if code else f"RNA #{index}"
    if woreda:
        title += f" ({woreda})"

    return KoboRapidNeedsDetail(
        id=strawberry.ID(str(sub.id)),
        kobo_id=sub.kobo_id,
        emergency_code=code,
        index=index,
        title=title,
        submission_time=sub.submission_time,
        reporting_branch=labels.resolve_one("context/reporting_branch", raw.get("context/reporting_branch")),
        region=labels.resolve_one("location/region", raw.get("location/region")),
        zone=labels.resolve_one("location/zone", raw.get("location/zone")),
        woreda=woreda,
        kebele=_humanize(raw.get("location/kebele")),
        people_in_need=_to_int_or_none(raw.get("ppl_impact_group/ppl_in_need")),
        people_affected=_to_int_or_none(raw.get("ppl_impact_group/ppl_affected")),
        people_displaced=_to_int_or_none(raw.get("ppl_impact_group/ppl_affected_displaced")),
        people_affected_non_displaced=_to_int_or_none(raw.get("ppl_impact_group/ppl_affected_non-displaced")),
        top_affected_groups=labels.collect(
            raw,
            ["affected_groups/affected1", "affected_groups/affected2", "affected_groups/affected3"],
        ),
        priority_sectors=labels.collect(
            raw,
            ["priority_sectors/sector1", "priority_sectors/sector2", "priority_sectors/sector3"],
        ),
        vulnerable_groups=labels.collect(
            raw,
            ["vulnerable_groups/vulnerable1", "vulnerable_groups/vulnerable2", "vulnerable_groups/vulnerable3"],
        ),
        response_modalities=labels.collect(
            raw,
            ["response_modalities/modality1", "response_modalities/modality2", "response_modalities/modality3"],
        ),
    )


def build_field_report_detail(submission_id: str) -> KoboFieldReportDetail | None:
    """Full detail for one approved Emergency Field Report, with resolved action labels."""
    sub = KoboSubmission.objects.filter(
        id=submission_id,
        form=KoboForm.EMERGENCY_FIELD,
        validation_status=VALIDATION_STATUS_APPROVED,
    ).first()
    if sub is None:
        return None

    raw = sub.raw
    labels = FormLabels.load(KoboForm.EMERGENCY_FIELD)
    code = sub.emergency_code
    index = _report_index(sub)
    title = f"{code} — Field Report #{index}" if code else f"Field Report #{index}"

    region = labels.resolve_one("location/region-one", raw.get("location/region-one"))
    woreda = labels.resolve_one("location/woreda-one", raw.get("location/woreda-one"))
    location = f"{woreda} woreda, {region}" if (woreda and region) else (woreda or region)

    # The Field form only carries a branch code, so the branch shown is the
    # parent alert's region (per the agreed design).
    prepositioned = raw.get("branch_sitrep/resources_group/resources_water_prepositioned_used")
    prepositioned_display = {"yes": "Yes", "no": "No"}.get(str(prepositioned).lower()) if prepositioned else None

    return KoboFieldReportDetail(
        id=strawberry.ID(str(sub.id)),
        kobo_id=sub.kobo_id,
        emergency_code=code,
        index=index,
        title=title,
        submission_time=sub.submission_time,
        reporting_branch=_alert_region(code),
        region=region,
        location=location,
        reporting_period_start=raw.get("context/period-start_date"),
        reporting_period_end=raw.get("context/period-end_date"),
        reporting_days=_to_int_or_none(raw.get("context/reporting_days")),
        people_reached=_to_int_or_none(raw.get("branch_sitrep/reached_population/g_reach")),
        volunteers=_to_int_or_none(raw.get("branch_sitrep/resources_group/resources_volunteers")),
        staff=_to_int_or_none(raw.get("branch_sitrep/resources_group/resources_staff")),
        bdrt=_to_int_or_none(raw.get("branch_sitrep/resources_group/resources_BDRT")),
        # Faithful to the mockup's phrasing; "third-party" appended when such sources exist.
        type_of_reported_information=(
            "ERCS field teams and third-party sources" if raw.get("latest_info/third_party_sources") else "ERCS field teams"
        ),
        prepositioned_stocks_used=prepositioned_display,
        response_actions=labels.resolve_many("branch_sitrep/action_taken", raw.get("branch_sitrep/action_taken")),
        latest_developments=(
            raw.get("latest_info/info_primary-source") or raw.get("branch_sitrep/action_taken_description")
        ),
    )
