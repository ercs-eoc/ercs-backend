"""Admin for the Kobo mirror.

The mirrored data is owned entirely by the sync job: ``KoboSubmission`` rows are
re-upserted from Kobo on every run and pruned when Kobo drops them, and
``KoboSyncState`` is rewritten each run. An edit made here would be silently
reverted the next night, so the admin exposes the data for inspection only.

The one exception is ``KoboHazard.go_disaster_type_id``: a mapping Kobo knows
nothing about, so it is curated here and never touched by the sync.
"""

import typing

from django.contrib import admin
from django.http import HttpRequest

from apps.kobo.models import KoboFormSchema, KoboHazard, KoboSubmission, KoboSyncState


class ReadOnlyAdmin(admin.ModelAdmin):  # type: ignore[reportMissingTypeArgument]
    """Inspect-only: Django renders the detail view read-only without change perms."""

    @typing.override
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @typing.override
    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    @typing.override
    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        # A deleted row would simply reappear on the next sync.
        return False


@admin.register(KoboSubmission)
class KoboSubmissionAdmin(ReadOnlyAdmin):
    list_display = ("kobo_id", "form", "validation_status", "emergency_code", "submission_time")
    list_filter = ("form", "validation_status")
    search_fields = ("kobo_id", "emergency_code")
    date_hierarchy = "submission_time"
    list_select_related = ("region",)


@admin.register(KoboSyncState)
class KoboSyncStateAdmin(ReadOnlyAdmin):
    list_display = ("form", "last_status", "last_fetched_at", "record_count")


@admin.register(KoboFormSchema)
class KoboFormSchemaAdmin(ReadOnlyAdmin):
    list_display = ("form", "asset_uid", "fetched_at")


@admin.register(KoboHazard)
class KoboHazardAdmin(admin.ModelAdmin):  # type: ignore[reportMissingTypeArgument]
    """Only the GO mapping is editable; the rest is mirrored from the Kobo form."""

    list_display = ("label", "code", "go_disaster_type_id", "is_active")
    list_editable = ("go_disaster_type_id",)
    list_filter = ("is_active",)
    search_fields = ("code", "label")
    fields = ("code", "label", "is_active", "go_disaster_type_id")
    readonly_fields = ("code", "label", "is_active")

    @typing.override
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @typing.override
    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        # A deleted row would simply reappear on the next sync, without its GO mapping.
        return False
