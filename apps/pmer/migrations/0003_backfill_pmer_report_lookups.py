from django.db import migrations

# Labels of the removed `PmerReportCategory` / `PmerReportDocumentType` enums,
# keyed by their stored integer value, so existing reports keep their category
# and document type.
LEGACY_CATEGORIES = {
    10: "DPR (Disaster Preparedness Report)",
    20: "DRR (Disaster Risk Reduction)",
    30: "Health & WASH",
    40: "Volunteer Service / Membership",
}
LEGACY_DOCUMENT_TYPES = {
    10: "Strategic Plan",
    20: "Annual Plan",
    30: "Annual Report",
    40: "Mid-term Review Report",
}


def forwards(apps, schema_editor):
    PmerCategory = apps.get_model("pmer", "PmerCategory")
    PmerDocumentType = apps.get_model("pmer", "PmerDocumentType")
    PmerReport = apps.get_model("pmer", "PmerReport")

    # Only values referenced by existing reports are seeded; everything else is
    # now managed by users through the API.
    for value in PmerReport.objects.values_list("category", flat=True).distinct():
        category, _ = PmerCategory.objects.get_or_create(name=LEGACY_CATEGORIES.get(value, f"Category {value}"))
        PmerReport.objects.filter(category=value).update(category_new=category)
    for value in PmerReport.objects.values_list("report_type", flat=True).distinct():
        document_type, _ = PmerDocumentType.objects.get_or_create(
            name=LEGACY_DOCUMENT_TYPES.get(value, f"Document Type {value}"),
        )
        PmerReport.objects.filter(report_type=value).update(report_type_new=document_type)


def backwards(apps, schema_editor):
    PmerReport = apps.get_model("pmer", "PmerReport")
    category_values = {name: value for value, name in LEGACY_CATEGORIES.items()}
    document_type_values = {name: value for value, name in LEGACY_DOCUMENT_TYPES.items()}
    for report in PmerReport.objects.select_related("category_new", "report_type_new"):
        # Rows created after the switch have no legacy value; fall back to the first choice.
        report.category = category_values.get(report.category_new.name, 10)
        report.report_type = document_type_values.get(report.report_type_new.name, 10)
        report.save(update_fields=["category", "report_type"])


class Migration(migrations.Migration):
    dependencies = [
        ("pmer", "0002_user_managed_category_and_document_type"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
