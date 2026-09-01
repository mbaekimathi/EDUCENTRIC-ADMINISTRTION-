from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0042_exam_mark_out_of_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="generatedexamtimetable",
            name="deadline",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="generatedexamtimetable",
            name="status",
            field=models.CharField(
                choices=[
                    ("IN_SESSION", "In session"),
                    ("MARKING", "Marking"),
                    ("ANALYSING", "Analysing"),
                    ("PUBLISHED", "Published"),
                ],
                default="IN_SESSION",
                max_length=20,
            ),
        ),
    ]
