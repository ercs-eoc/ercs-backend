import typing

from django.core.files import File
from django.core.validators import FileExtensionValidator
from rest_framework import serializers

from utils.validators import validate_image_size, validate_report_file_size

from .models import Link, Report, ReportContentType, ReportVisibility, ThematicArea

ALLOWED_FILE_EXTENSIONS: list[str] = ["pdf", "doc", "docx", "png", "jpg", "jpeg"]

validate_file_extension = FileExtensionValidator(
    allowed_extensions=ALLOWED_FILE_EXTENSIONS,
    message="Unsupported file type. Allowed file types are: %(allowed_extensions)s.",
)


class LinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Link
        fields = ["title", "description", "url", "link_type"]


class ThematicAreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ThematicArea
        fields = ["name"]


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = [
            "title",
            "description",
            "cover_image",
            "content_type",
            "file",
            "iframe_url",
            "visibility",
            "report_type",
            "thematic_area",
            "region",
            "disaster_type",
            "owner",
            "uploaded_by",
            "published_at",
        ]
        extra_kwargs = {
            "uploaded_by": {"required": False},
        }

    def validate_cover_image(self, value: File) -> File:
        return validate_image_size(value)

    def validate_file(self, value: File) -> File:
        validate_report_file_size(value)
        validate_file_extension(value)
        return value

    def validate_visibility(self, value: int) -> int:
        if self.instance and self.instance.visibility == ReportVisibility.PRIVATE and value == ReportVisibility.PUBLIC:
            raise serializers.ValidationError("Cannot change visibility from PRIVATE to PUBLIC.")
        return value

    @typing.override
    def validate(self, attrs: dict) -> dict:
        content_type = attrs.get("content_type", getattr(self.instance, "content_type", None))
        file = attrs.get("file", getattr(self.instance, "file", None))
        iframe_url = attrs.get("iframe_url", getattr(self.instance, "iframe_url", None))
        report_type = attrs.get("report_type", getattr(self.instance, "report_type", Report.ReportType.REPORT))
        thematic_area = attrs.get("thematic_area", getattr(self.instance, "thematic_area", None))

        if report_type == Report.ReportType.REPORT and not thematic_area:
            raise serializers.ValidationError(
                {"thematic_area": "A thematic area is required when report type is REPORT."},
            )

        if content_type == ReportContentType.FILE and not file:
            raise serializers.ValidationError({"file": "A file is required when content_type is FILE."})
        if content_type == ReportContentType.IFRAME and not iframe_url:
            raise serializers.ValidationError({"iframe_url": "An iframe URL is required when content_type is IFRAME."})
        return attrs

    @typing.override
    def create(self, validated_data: dict) -> Report:
        request = self.context.get("request")
        if request and hasattr(request, "user") and request.user.is_authenticated:
            validated_data.setdefault("uploaded_by", request.user)
        return super().create(validated_data)
