"""Fetch ERCS EOC Kobo submissions and reconcile them into the local store.

Design (see ``backend/docs/kobo-api.md`` and the ADR-style notes below):

- **Three confirmed forms** — Alert, RNA, Field — pulled with ``KOBO_ACCESS_TOKEN``.
- **Fetch-before-mutate**: every submission is downloaded first; only then do we
  touch the DB, so a failed/partial fetch never wipes good data.
- **Reconcile, not additive**: within one transaction per form we upsert each
  record by ``(asset_uid, kobo_id)`` and prune every stored row *for that form*
  that Kobo no longer returns. Pruning is scoped by ``form``, not ``asset_uid``,
  so re-pointing a form at a new asset in ``FORM_SPECS`` cleans up the rows from
  the old asset instead of leaving them behind to be double-counted by the stats
  layer (which reads by ``form``). A row's UUID pk + ``created_at`` survive runs.
- **Never prune on an empty success**: a 200 with zero results (asset re-pointed,
  emptied, or a scope change) would otherwise wipe the form and be recorded as a
  success. That case is treated as a failure and the stored rows are kept.
- **Per-form isolation**: one form failing is logged (and reported to Sentry) but
  does not block the others; that form keeps its previous data.
- **Store all rows**: ``validation_status`` is kept per row so the stats layer can
  filter to approved submissions.
"""

import datetime
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import requests
import sentry_sdk
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.geo.models import AdminArea, AdminAreaLevel
from apps.kobo.labels import build_label_maps
from apps.kobo.models import KoboForm, KoboFormSchema, KoboHazard, KoboSubmission, KoboSyncState

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 60.0
PAGE_LIMIT = 2000

# The Emergency Alert question whose choices are mirrored into `KoboHazard`.
HAZARD_FIELD = "hazard"


@dataclass(frozen=True)
class FormSpec:
    """Where a form lives and how to derive its promoted columns from a record."""

    form: KoboForm
    asset_uid: str
    # First present key wins — used to derive the promoted `emergency_code` column.
    emergency_code_keys: tuple[str, ...]
    # First present key wins — the reporting region name, matched to an AdminArea.
    region_keys: tuple[str, ...]


FORM_SPECS: tuple[FormSpec, ...] = (
    FormSpec(
        form=KoboForm.EMERGENCY_ALERT,
        asset_uid="aydYC8AYCDuX7y4PwfvgrX",
        emergency_code_keys=("emergency_code/unique_code",),
        region_keys=("geo/region-one",),
    ),
    FormSpec(
        form=KoboForm.RAPID_NEEDS_ASSESSMENT,
        asset_uid="aPuV7tDb9mdRiK8hUhkxJC",
        emergency_code_keys=("context/emergency-selection", "location/alert_code"),
        region_keys=("location/region",),
    ),
    FormSpec(
        form=KoboForm.EMERGENCY_FIELD,
        asset_uid="aby6sxp4DyEiohs4XMn7Mu",
        emergency_code_keys=("context/emergency-selection", "location/alert_code"),
        region_keys=("location/region-one",),
    ),
)


@dataclass
class FormResult:
    form: KoboForm
    ok: bool
    created: int = 0
    updated: int = 0
    deleted: int = 0
    total: int = 0
    error: str = ""


class KoboConfigError(RuntimeError):
    """The syncer is not configured to talk to Kobo at all.

    Distinct from a per-form failure: no form can succeed, so the run aborts up
    front instead of failing each form in turn (three stack traces, three Sentry
    events and three ``FAILURE`` rows for one missing setting).
    """


@dataclass
class KoboSyncer:
    """Fetches and reconciles Kobo submissions. Safe to run repeatedly."""

    stdout: Any = None
    style: Any = None
    _region_cache: dict[str, AdminArea] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Case-insensitive, underscore-insensitive lookup of REGION admin areas.
        # `.iterator()` streams instead of caching the whole queryset in the
        # QuerySet's result cache — we only need each row once, on the way in.
        for area in AdminArea.objects.filter(level=AdminAreaLevel.REGION).iterator():
            self._region_cache[self._normalize_region(area.name)] = area

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    @staticmethod
    def check_config() -> None:
        """Raise :class:`KoboConfigError` unless we can reach Kobo at all."""
        missing = [name for name in ("KOBO_ACCESS_TOKEN", "KOBO_DOMAIN") if not getattr(settings, name, None)]
        if missing:
            raise KoboConfigError(
                f"{', '.join(missing)} is not configured — set it in the environment "
                "(see main/settings.py; the token is a per-environment secret).",
            )

    def run(self, dry_run: bool = False, only: KoboForm | None = None) -> list[FormResult]:
        self.check_config()
        results: list[FormResult] = []
        for spec in FORM_SPECS:
            if only is not None and spec.form != only:
                continue
            results.append(self.sync_form(spec, dry_run=dry_run))
            if not dry_run:
                self.sync_schema(spec)
        return results

    def sync_schema(self, spec: FormSpec) -> None:
        """Fetch the form's choice labels and store them (best-effort).

        Independent of the data sync and never fatal: a failure keeps the last
        stored labels (or, first time, leaves values shown as humanized codes).
        """
        label = KoboForm(spec.form).label
        try:
            content = self._fetch_schema(spec.asset_uid)
            labels = build_label_maps(content)
            KoboFormSchema.objects.update_or_create(
                form=spec.form,
                defaults={"asset_uid": spec.asset_uid, "labels": labels, "fetched_at": timezone.now()},
            )
            self._ok(f"  {label}: schema labels updated ({len(labels['choices'])} choice lists)")
            if spec.form == KoboForm.EMERGENCY_ALERT:
                self.sync_hazards(labels)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            logger.exception("Kobo schema fetch failed for %s (%s)", label, spec.asset_uid)
            self._warn(f"  {label}: SCHEMA FETCH FAILED — {exc} (existing labels kept)")

    def sync_hazards(self, labels: dict[str, Any]) -> None:
        """Mirror the Emergency Alert hazard choices into :class:`KoboHazard`.

        Upserts each choice (code + label) and deactivates the ones no longer in
        the form. ``go_disaster_type_id`` is admin-curated and left untouched. A
        schema without the hazard list keeps the stored hazards rather than
        deactivating them all.
        """
        field_spec = labels.get("fields", {}).get(HAZARD_FIELD)
        choices: dict[str, str] = labels.get("choices", {}).get(field_spec["list"], {}) if field_spec else {}
        if not choices:
            logger.warning("Kobo schema has no `%s` choices; existing hazards kept", HAZARD_FIELD)
            self._warn(f"  No `{HAZARD_FIELD}` choices in the Emergency Alert schema (existing hazards kept)")
            return

        with transaction.atomic():
            for code, label in choices.items():
                KoboHazard.objects.update_or_create(code=code, defaults={"label": label, "is_active": True})
            deactivated = KoboHazard.objects.filter(is_active=True).exclude(code__in=choices).update(is_active=False)
        self._ok(f"  Hazards updated ({len(choices)} active, {deactivated} deactivated)")

    def sync_form(self, spec: FormSpec, dry_run: bool = False) -> FormResult:
        self.check_config()  # `sync_form` is also called directly (tests, one-off scripts).
        label = KoboForm(spec.form).label
        try:
            records = list(self._fetch_all(spec.asset_uid))  # network first, before any DB write
        except KoboConfigError:
            raise  # Not this form's failure — abort the run rather than record one.
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            logger.exception("Kobo fetch failed for %s (%s)", label, spec.asset_uid)
            self._record_state(spec, ok=False, error=str(exc), count=None, dry_run=dry_run)
            self._warn(f"  {label}: FETCH FAILED — {exc} (existing rows kept)")
            return FormResult(form=spec.form, ok=False, error=str(exc))

        # An empty-but-successful response would prune the whole form. Kobo
        # returning nothing for a form that has stored rows means something is
        # wrong upstream (asset re-pointed/emptied, token scope changed), not
        # that every submission was deleted — keep what we have and fail loudly.
        if not records and KoboSubmission.objects.filter(form=spec.form).exists():
            error = "Kobo returned 0 records for a form that has stored rows; refusing to prune."
            sentry_sdk.capture_message(f"Kobo sync: {error} ({label}, {spec.asset_uid})")
            logger.error("Kobo sync: %s (%s, %s)", error, label, spec.asset_uid)
            self._record_state(spec, ok=False, error=error, count=None, dry_run=dry_run)
            self._warn(f"  {label}: EMPTY RESPONSE — {error} (existing rows kept)")
            return FormResult(form=spec.form, ok=False, error=error)

        try:
            with transaction.atomic():
                result = self._reconcile(spec, records)
                if dry_run:
                    transaction.set_rollback(True)
                else:
                    self._record_state(spec, ok=True, error="", count=result.total, dry_run=dry_run)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            logger.exception("Kobo reconcile failed for %s", label)
            self._record_state(spec, ok=False, error=str(exc), count=None, dry_run=dry_run)
            self._warn(f"  {label}: RECONCILE FAILED — {exc} (existing rows kept)")
            return FormResult(form=spec.form, ok=False, error=str(exc))

        self._ok(
            f"  {label}: {result.created} created, {result.updated} updated, "
            f"{result.deleted} pruned ({result.total} total)" + (" [dry-run rolled back]" if dry_run else ""),
        )
        return result

    # ------------------------------------------------------------------
    # Reconcile
    # ------------------------------------------------------------------

    def _reconcile(self, spec: FormSpec, records: list[dict[str, Any]]) -> FormResult:
        created = updated = 0
        seen: set[int] = set()

        for rec in records:
            kobo_id = int(rec["_id"])
            seen.add(kobo_id)
            _, was_created = KoboSubmission.objects.update_or_create(
                asset_uid=spec.asset_uid,
                kobo_id=kobo_id,
                defaults={
                    "form": spec.form,
                    "submission_time": self._parse_dt(rec.get("_submission_time")),
                    "validation_status": (rec.get("_validation_status") or {}).get("uid", "") or "",
                    "emergency_code": self._first(rec, spec.emergency_code_keys),
                    "region": self._match_region(self._first(rec, spec.region_keys)),
                    "raw": rec,
                },
            )
            created += was_created
            updated += not was_created

        # Scoped by `form`, not `asset_uid`: rows left over from a previously
        # configured asset for this form must go too, otherwise the stats layer
        # (which reads by `form`) counts them alongside the current asset's rows.
        deleted, _ = (
            KoboSubmission.objects.filter(form=spec.form).exclude(asset_uid=spec.asset_uid, kobo_id__in=seen).delete()
        )
        return FormResult(
            form=spec.form,
            ok=True,
            created=created,
            updated=updated,
            deleted=deleted,
            total=len(seen),
        )

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _fetch_all(self, asset_uid: str) -> Iterator[dict[str, Any]]:
        self.check_config()
        headers = {"Authorization": f"Token {settings.KOBO_ACCESS_TOKEN}"}
        url: str | None = f"{settings.KOBO_DOMAIN}/api/v2/assets/{asset_uid}/data/?format=json&limit={PAGE_LIMIT}"
        while url:
            resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            yield from data["results"]
            url = data.get("next")

    def _fetch_schema(self, asset_uid: str) -> dict[str, Any]:
        """The asset's ``content`` (``survey`` + ``choices``) — the choice-label source."""
        self.check_config()
        headers = {"Authorization": f"Token {settings.KOBO_ACCESS_TOKEN}"}
        url = f"{settings.KOBO_DOMAIN}/api/v2/assets/{asset_uid}/?format=json"
        resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("content", {})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_dt(value: Any) -> datetime.datetime | None:
        """Kobo `_submission_time` is naive UTC; return a tz-aware datetime."""
        if not value:
            return None
        dt = parse_datetime(str(value))
        if dt is not None and timezone.is_naive(dt):
            dt = timezone.make_aware(dt, datetime.UTC)
        return dt

    @staticmethod
    def _first(rec: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = rec.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def _normalize_region(name: str | None) -> str:
        return (name or "").replace("_", " ").strip().casefold()

    def _match_region(self, name: str | None) -> AdminArea | None:
        if not name:
            return None
        area = self._region_cache.get(self._normalize_region(name))
        if area is None:
            logger.warning("Kobo sync: no AdminArea REGION match for %r", name)
        return area

    def _record_state(self, spec: FormSpec, ok: bool, error: str, count: int | None, dry_run: bool = False) -> None:
        if dry_run:
            # The success path is rolled back with the reconcile transaction; the
            # failure paths run outside it, so they have to opt out explicitly.
            return
        defaults: dict[str, Any] = {
            "asset_uid": spec.asset_uid,
            "last_status": KoboSyncState.Status.SUCCESS if ok else KoboSyncState.Status.FAILURE,
            "last_error": error,
        }
        if ok:
            defaults["last_fetched_at"] = timezone.now()
            defaults["record_count"] = count or 0
        KoboSyncState.objects.update_or_create(form=spec.form, defaults=defaults)

    def _ok(self, msg: str) -> None:
        logger.info(msg)
        if self.stdout is not None:
            self.stdout.write(self.style.SUCCESS(msg) if self.style else msg)

    def _warn(self, msg: str) -> None:
        logger.warning(msg)
        if self.stdout is not None:
            self.stdout.write(self.style.WARNING(msg) if self.style else msg)
