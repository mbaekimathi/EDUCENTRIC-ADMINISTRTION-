from decimal import Decimal

from django.db import migrations, models


DEFAULT_GRADE_BANDS = [
    {
        "code": "EE1",
        "mark_level": "EXCEEDING EXPECTATION 1",
        "meaning": "EXCELLENT",
        "description": "7-9",
        "points": 8,
        "start_percent": 91,
        "end_percent": 100,
    },
    {
        "code": "EE2",
        "mark_level": "EXCEEDING EXPECTATION 2",
        "meaning": "VERY HIGH PERFORMANCE",
        "description": "7-9",
        "points": Decimal("7.00"),
        "start_percent": Decimal("75.00"),
        "end_percent": Decimal("90.00"),
    },
    {
        "code": "ME1",
        "mark_level": "MEETING EXPECTATION 1",
        "meaning": "HIGH PERFORMANCE",
        "description": "7-9",
        "points": Decimal("6.00"),
        "start_percent": Decimal("57.96"),
        "end_percent": Decimal("74.00"),
    },
    {
        "code": "ME2",
        "mark_level": "MEETING EXPECTATION 2",
        "meaning": "AVERAGE PERFORMANCE",
        "description": "7-9",
        "points": Decimal("5.00"),
        "start_percent": Decimal("41.00"),
        "end_percent": Decimal("57.00"),
    },
    {
        "code": "AE1",
        "mark_level": "APPROACHING EXPECTATION 1",
        "meaning": "A RELATIVELY BELOW AVERAGE PERFORMANCE",
        "description": "7-9",
        "points": Decimal("4.00"),
        "start_percent": Decimal("31.00"),
        "end_percent": Decimal("40.00"),
    },
    {
        "code": "AE2",
        "mark_level": "APPROACHING EXPECTATION 2",
        "meaning": "APPROACHING EXPECTATION",
        "description": "7-9",
        "points": Decimal("3.00"),
        "start_percent": Decimal("21.00"),
        "end_percent": Decimal("30.00"),
    },
    {
        "code": "BE1",
        "mark_level": "BELOW EXPECTATION",
        "meaning": "A BELOW EXPECTATION PERFORMANCE",
        "description": "7-9",
        "points": Decimal("2.00"),
        "start_percent": Decimal("11.00"),
        "end_percent": Decimal("20.00"),
    },
    {
        "code": "BE2",
        "mark_level": "BELOW EXPECTATION 2",
        "meaning": "VERY LOW SCORE",
        "description": "7-9",
        "points": Decimal("1.00"),
        "start_percent": Decimal("1.00"),
        "end_percent": Decimal("10.00"),
    },
]


def seed_grade_bands(apps, schema_editor):
    GradeBand = apps.get_model("curriculum", "GradeBand")
    GradeBand.objects.all().delete()
    GradeBand.objects.bulk_create(
        [GradeBand(**row) for row in DEFAULT_GRADE_BANDS]
    )


def clear_grade_bands(apps, schema_editor):
    GradeBand = apps.get_model("curriculum", "GradeBand")
    GradeBand.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("curriculum", "0015_exam_timetable_sessions"),
    ]

    operations = [
        migrations.DeleteModel(name="GradeBand"),
        migrations.CreateModel(
            name="GradeBand",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.CharField(max_length=20, unique=True)),
                ("mark_level", models.CharField(max_length=120)),
                ("meaning", models.CharField(max_length=160)),
                ("description", models.CharField(blank=True, max_length=160)),
                (
                    "points",
                    models.DecimalField(decimal_places=2, default=0, max_digits=5),
                ),
                (
                    "start_percent",
                    models.DecimalField(
                        decimal_places=2, max_digits=5, verbose_name="start %"
                    ),
                ),
                (
                    "end_percent",
                    models.DecimalField(
                        decimal_places=2, max_digits=5, verbose_name="end %"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "grade band",
                "verbose_name_plural": "grade bands",
                "ordering": ["-end_percent", "-start_percent", "code"],
            },
        ),
        migrations.AddConstraint(
            model_name="gradeband",
            constraint=models.CheckConstraint(
                check=models.Q(end_percent__gte=models.F("start_percent")),
                name="grade_band_end_gte_start",
            ),
        ),
        migrations.RunPython(seed_grade_bands, clear_grade_bands),
    ]
