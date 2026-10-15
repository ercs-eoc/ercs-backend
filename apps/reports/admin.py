from django.contrib import admin

from .models import DocumentExtraction, DocumentExtractionRun, Link, Report, ThematicArea


@admin.register(ThematicArea)
class ThematicAreaAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "created_at"]
    search_fields = ["name"]
    ordering = ["name"]


@admin.register(DocumentExtraction)
class DocumentExtractionAdmin(admin.ModelAdmin):
    list_display = ["report", "status", "chunk_type", "page_number", "created_at", "updated_at"]
    list_filter = ["status"]
    readonly_fields = ["report", "created_at", "chunk_type", "page_number", "updated_at"]
    ordering = ["-created_at"]


@admin.register(DocumentExtractionRun)
class DocumentExtractionRunAdmin(admin.ModelAdmin):
    list_display = [
        "report",
        "status",
        "trigger",
        "created_at",
        "queue_wait",
        "duration",
    ]
    list_filter = ["status", "trigger", "doc_summary_generated"]
    search_fields = ["report__title", "celery_task_id"]
    list_select_related = ["report"]


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ["title", "link_type", "url", "created_at"]
    list_filter = ["link_type"]
    search_fields = ["title", "description", "url"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["title"]


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "content_type",
        "visibility",
        "thematic_area",
        "region",
        "disaster_type",
        "uploaded_by",
        "published_at",
        "created_at",
    ]
    list_filter = ["content_type", "visibility", "report_type", "thematic_area", "disaster_type"]
    search_fields = ["title", "description", "owner"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]
