import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("admissions", "0003_student_is_suspended"),
        ("curriculum", "0028_exam_timetable_dates_year_term"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExamMark",
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
                ("marks", models.PositiveIntegerField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "generation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="marks",
                        to="curriculum.generatedexamtimetable",
                    ),
                ),
                (
                    "learning_area",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="exam_marks",
                        to="curriculum.learningarea",
                        verbose_name="subject",
                    ),
                ),
                (
                    "student",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="exam_marks",
                        to="admissions.student",
                    ),
                ),
            ],
            options={
                "verbose_name": "exam mark",
                "verbose_name_plural": "exam marks",
                "ordering": [
                    "student__last_name",
                    "student__first_name",
                    "learning_area__display_order",
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=["generation", "student", "learning_area"],
                        name="unique_exam_mark_per_student_and_subject",
                    ),
                ],
            },
        ),
    ]
