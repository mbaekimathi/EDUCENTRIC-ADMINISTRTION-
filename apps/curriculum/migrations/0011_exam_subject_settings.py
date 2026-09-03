from django.db import migrations, models
import django.db.models.deletion

from apps.curriculum.compat import check_constraint


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0010_learningarea_total_marks"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExamSubjectSetting",
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
                (
                    "out_of_marks",
                    models.DecimalField(
                        decimal_places=2,
                        default=100,
                        max_digits=7,
                        verbose_name="out of marks",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "academic_level",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="exam_subject_settings",
                        to="curriculum.academiclevel",
                    ),
                ),
                (
                    "learning_area",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="exam_settings",
                        to="curriculum.learningarea",
                    ),
                ),
            ],
            options={
                "verbose_name": "exam subject setting",
                "verbose_name_plural": "exam subject settings",
                "ordering": [
                    "academic_level__order",
                    "learning_area__display_order",
                    "learning_area__name",
                ],
            },
        ),
        migrations.CreateModel(
            name="CombinedExamSubject",
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
                ("name", models.CharField(max_length=120)),
                ("code", models.CharField(max_length=40)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "academic_level",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="combined_exam_subjects",
                        to="curriculum.academiclevel",
                    ),
                ),
                (
                    "first_subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="first_combined_subjects",
                        to="curriculum.examsubjectsetting",
                    ),
                ),
                (
                    "second_subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="second_combined_subjects",
                        to="curriculum.examsubjectsetting",
                    ),
                ),
            ],
            options={
                "verbose_name": "combined exam subject",
                "verbose_name_plural": "combined exam subjects",
                "ordering": ["academic_level__order", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="examsubjectsetting",
            constraint=models.UniqueConstraint(
                fields=("academic_level", "learning_area"),
                name="unique_exam_setting_per_level_and_learning_area",
            ),
        ),
        migrations.AddConstraint(
            model_name="combinedexamsubject",
            constraint=models.UniqueConstraint(
                fields=("academic_level", "code"),
                name="unique_combined_exam_subject_code_per_level",
            ),
        ),
        migrations.AddConstraint(
            model_name="combinedexamsubject",
            constraint=check_constraint(
                condition=~models.Q(
                    ("first_subject", models.F("second_subject")),
                ),
                name="combined_exam_subjects_must_differ",
            ),
        ),
    ]
