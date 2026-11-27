import uuid

import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ("pmer", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PmerCategory",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255, unique=True)),
            ],
            options={
                "verbose_name": "PMER Category",
                "verbose_name_plural": "PMER Categories",
            },
        ),
        migrations.CreateModel(
            name="PmerDocumentType",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255, unique=True)),
            ],
            options={
                "verbose_name": "PMER Document Type",
                "verbose_name_plural": "PMER Document Types",
            },
        ),
        # Old integer columns are relaxed so the reverse path can add them back empty.
        migrations.AlterField(
            model_name="pmerreport",
            name="category",
            field=models.IntegerField(null=True),
        ),
        migrations.AlterField(
            model_name="pmerreport",
            name="report_type",
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name="pmerreport",
            name="category_new",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="pmer.pmercategory",
            ),
        ),
        migrations.AddField(
            model_name="pmerreport",
            name="report_type_new",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="pmer.pmerdocumenttype",
            ),
        ),
    ]
