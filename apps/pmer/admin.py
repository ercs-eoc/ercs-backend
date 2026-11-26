from django.contrib import admin

from .models import PmerCategory, PmerDocumentType, PmerReport


@admin.register(PmerCategory)
class PmerCategoryAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "created_at"]
    search_fields = ["name"]
    ordering = ["name"]


@admin.register(PmerDocumentType)
class PmerDocumentTypeAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "created_at"]
    search_fields = ["name"]
    ordering = ["name"]


@admin.register(PmerReport)
class PmerReportAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "report_type", "visibility"]
    list_filter = ["category", "report_type", "visibility"]
    search_fields = ["title"]
    autocomplete_fields = ["category", "report_type"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]
