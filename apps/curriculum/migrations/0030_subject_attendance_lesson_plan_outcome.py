import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("admissions", "0003_student_is_suspended"),
        ("curriculum", "0029_exam_mark"),
        ("employees", "0010_numeric_employment_numbers"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClassSubjectLessonPlan",
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
                ("title", models.CharField(blank=True, max_length=255)),
                ("objectives", models.TextField(blank=True)),
                ("content", models.TextField(blank=True, verbose_name="lesson content")),
                ("resources", models.TextField(blank=True)),
                ("homework", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "allocation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lesson_plan",
                        to="curriculum.classsubjectallocation",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_lesson_plans",
                        to="employees.employee",
                    ),
                ),
            ],
            options={
                "verbose_name": "class subject lesson plan",
                "verbose_name_plural": "class subject lesson plans",
            },
        ),
        migrations.CreateModel(
            name="ClassSubjectOutcome",
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
                ("outcome", models.TextField(blank=True, verbose_name="class subject outcome")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "allocation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subject_outcome",
                        to="curriculum.classsubjectallocation",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_subject_outcomes",
                        to="employees.employee",
                    ),
                ),
            ],
            options={
                "verbose_name": "class subject outcome",
                "verbose_name_plural": "class subject outcomes",
            },
        ),
        migrations.CreateModel(
            name="SubjectAttendanceSession",
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
                ("lesson_date", models.DateField()),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "allocation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attendance_sessions",
                        to="curriculum.classsubjectallocation",
                    ),
                ),
                (
                    "taken_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="subject_attendance_sessions",
                        to="employees.employee",
                    ),
                ),
            ],
            options={
                "verbose_name": "subject attendance session",
                "verbose_name_plural": "subject attendance sessions",
                "ordering": ["-lesson_date", "-updated_at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=["allocation", "lesson_date"],
                        name="unique_subject_attendance_per_day",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SubjectAttendanceRecord",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("PRESENT", "Present"),
                            ("ABSENT", "Absent"),
                            ("LATE", "Late"),
                            ("EXCUSED", "Excused"),
                        ],
                        default="PRESENT",
                        max_length=10,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="records",
                        to="curriculum.subjectattendancesession",
                    ),
                ),
                (
                    "student",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subject_attendance_records",
                        to="admissions.student",
                    ),
                ),
            ],
            options={
                "verbose_name": "subject attendance record",
                "verbose_name_plural": "subject attendance records",
                "ordering": ["student__last_name", "student__first_name"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=["session", "student"],
                        name="unique_subject_attendance_per_student",
                    ),
                ],
            },
        ),
    ]
