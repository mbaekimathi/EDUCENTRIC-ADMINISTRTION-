from django.db import migrations, models


def assign_existing_sessions(apps, schema_editor):
    Profile = apps.get_model("curriculum", "ExamScheduleProfile")
    Session = apps.get_model("curriculum", "ExamTimetableSession")
    Level = apps.get_model("curriculum", "AcademicLevel")
    sessions = list(Session.objects.all())
    if not sessions:
        return
    profile = Profile.objects.create(name="GENERAL EXAM SESSION", category="GENERAL")
    through = Profile.academic_levels.through
    for level in Level.objects.filter(status="ACTIVE"):
        through.objects.create(
            examscheduleprofile_id=profile.id,
            academiclevel_id=level.id,
        )
    for session in sessions:
        session.profile_id = profile.id
        session.save(update_fields=["profile_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("curriculum", "0021_learning_schedule_lesson_end_time"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExamScheduleProfile",
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
                ("category", models.CharField(max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "academic_levels",
                    models.ManyToManyField(
                        related_name="exam_schedule_profiles",
                        to="curriculum.academiclevel",
                    ),
                ),
            ],
            options={
                "verbose_name": "exam schedule profile",
                "verbose_name_plural": "exam schedule profiles",
                "ordering": ["category", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="examscheduleprofile",
            constraint=models.UniqueConstraint(
                fields=("name", "category"),
                name="unique_exam_schedule_profile_per_category",
            ),
        ),
        migrations.AddField(
            model_name="examtimetablesession",
            name="profile",
            field=models.ForeignKey(
                null=True,
                on_delete=models.CASCADE,
                related_name="sessions",
                to="curriculum.examscheduleprofile",
            ),
        ),
        migrations.AddField(
            model_name="examtimetablesession",
            name="order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(assign_existing_sessions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="examtimetablesession",
            name="profile",
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name="sessions",
                to="curriculum.examscheduleprofile",
            ),
        ),
        migrations.AlterField(
            model_name="examtimetablesession",
            name="name",
            field=models.CharField(max_length=120),
        ),
        migrations.AlterModelOptions(
            name="examtimetablesession",
            options={
                "ordering": ["start_time", "order", "name"],
                "verbose_name": "exam timetable session",
                "verbose_name_plural": "exam timetable sessions",
            },
        ),
        migrations.AddConstraint(
            model_name="examtimetablesession",
            constraint=models.UniqueConstraint(
                fields=("profile", "name"),
                name="unique_exam_session_name_per_profile",
            ),
        ),
    ]
