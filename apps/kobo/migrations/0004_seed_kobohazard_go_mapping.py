from django.db import migrations

# Emergency Alert `hazard` choices as of the 2026-11 form, with the matching IFRC GO
# disaster type id (GO /api/v2/disaster_type/). Seeded once so the GO mapping exists
# before the first sync; afterwards the sync owns code/label/is_active and the GO id
# is curated in the admin. `None` = GO has no matching type.
HAZARDS = [
    # (code, label, go_disaster_type_id)
    ("conflict", "Conflict", 7),  # GO: Civil Unrest
    ("drought", "Drought", 20),
    ("earthquake", "Earth Quake", 2),
    ("epidemic", "Epidemic", 1),
    ("fire", "Fire", 15),
    ("flood", "Flood", 12),
    ("land_slide", "Land slide", 24),
    ("Locust", "Locust", 62),  # GO: Insect Infestation
    ("population-movement", "Population movement", 5),
    ("Sismic", "Sismic", 2),  # GO: Earthquake
    ("volcano", "Volcano", 8),  # GO: Volcanic Eruption
    ("Wind storm", "Wind storm", None),  # GO has no inland wind storm type
    ("other", "Other", 13),
]


def seed_hazards(apps, schema_editor):
    KoboHazard = apps.get_model("kobo", "KoboHazard")
    for code, label, go_disaster_type_id in HAZARDS:
        hazard, created = KoboHazard.objects.get_or_create(
            code=code,
            defaults={"label": label, "go_disaster_type_id": go_disaster_type_id},
        )
        # Never overwrite a mapping that has already been curated.
        if not created and hazard.go_disaster_type_id is None and go_disaster_type_id is not None:
            hazard.go_disaster_type_id = go_disaster_type_id
            hazard.save(update_fields=["go_disaster_type_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("kobo", "0003_kobohazard"),
    ]

    operations = [
        migrations.RunPython(seed_hazards, migrations.RunPython.noop),
    ]
