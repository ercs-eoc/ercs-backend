import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Drop the legacy integer columns and promote the FK columns filled in 0003.

    Schema changes, backfill and cleanup live in separate migrations because
    Postgres refuses to ALTER/index a table with pending deferred-FK trigger events
    in the same transaction as the data update.
    """

    dependencies = [
        ("pmer", "0003_backfill_pmer_report_lookups"),
    ]

    operations = [
        migrations.RemoveField(model_name="pmerreport", name="category"),
        migrations.RemoveField(model_name="pmerreport", name="report_type"),
        migrations.RenameField(model_name="pmerreport", old_name="category_new", new_name="category"),
        migrations.RenameField(model_name="pmerreport", old_name="report_type_new", new_name="report_type"),
        migrations.AlterField(
            model_name="pmerreport",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pmer_reports",
                to="pmer.pmercategory",
            ),
        ),
        migrations.AlterField(
            model_name="pmerreport",
            name="report_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pmer_reports",
                to="pmer.pmerdocumenttype",
            ),
        ),
    ]
