from django.db import migrations, models


def demote_duplicate_in_session_exams(apps, schema_editor):
    GeneratedExamTimetable = apps.get_model("curriculum", "GeneratedExamTimetable")
    in_session_exams = list(
        GeneratedExamTimetable.objects.filter(status="IN_SESSION").order_by("-created_at")
    )
    for exam in in_session_exams[1:]:
        exam.status = "SCHEDULED"
        exam.save(update_fields=["status"])


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0044_generated_exam_sitting_nullable_supervisor"),
    ]

    operations = [
        migrations.AlterField(
            model_name="generatedexamtimetable",
            name="status",
            field=models.CharField(
                choices=[
                    ("SCHEDULED", "Scheduled"),
                    ("IN_SESSION", "In session"),
                    ("MARKING", "Marking"),
                    ("ANALYSING", "Analysing"),
                    ("PUBLISHED", "Published"),
                ],
                default="SCHEDULED",
                max_length=20,
            ),
        ),
        migrations.RunPython(demote_duplicate_in_session_exams, migrations.RunPython.noop),
    ]
