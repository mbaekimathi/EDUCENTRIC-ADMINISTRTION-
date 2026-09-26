from django.db import migrations, models


ACTIVE_WORKFLOW_STATUSES = ("IN_SESSION", "MARKING", "ANALYSING")


def set_initial_current_exam(apps, schema_editor):
    GeneratedExamTimetable = apps.get_model("curriculum", "GeneratedExamTimetable")
    current = (
        GeneratedExamTimetable.objects.filter(status__in=ACTIVE_WORKFLOW_STATUSES)
        .order_by("-created_at")
        .first()
    )
    if current is not None:
        current.is_current = True
        current.save(update_fields=["is_current"])


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0047_gradeband_mariadb_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="generatedexamtimetable",
            name="is_current",
            field=models.BooleanField(default=False, verbose_name="current assessment"),
        ),
        migrations.RunPython(set_initial_current_exam, migrations.RunPython.noop),
    ]
