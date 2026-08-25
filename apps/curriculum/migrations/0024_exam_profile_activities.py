import datetime

from django.db import migrations, models


def seed_exam_day_times(apps, schema_editor):
    from apps.curriculum.schedule_preview import build_schedule_preview, minutes_to_time

    Profile = apps.get_model("curriculum", "ExamScheduleProfile")
    Session = apps.get_model("curriculum", "ExamTimetableSession")
    for profile in Profile.objects.all():
        sessions = list(
            Session.objects.filter(profile=profile).order_by("start_time", "order")
        )
        if sessions:
            first = sessions[0]
            last = sessions[-1]
            start = first.start_time
            duration = first.duration_minutes or 120
            end_minutes = (
                last.start_time.hour * 60
                + last.start_time.minute
                + (last.duration_minutes or duration)
            ) % (24 * 60)
            profile.first_exam_start_time = start
            profile.exam_session_duration_minutes = duration
            profile.last_exam_end_time = datetime.time(
                end_minutes // 60, end_minutes % 60
            )
            profile.save(
                update_fields=[
                    "first_exam_start_time",
                    "last_exam_end_time",
                    "exam_session_duration_minutes",
                ]
            )
        preview = build_schedule_preview(
            profile.first_exam_start_time,
            profile.exam_session_duration_minutes,
            [],
            last_class_end=profile.last_exam_end_time,
            period_label="Session",
            day_labels=["Exam day"],
            start_caption="first exam",
            end_caption="exam end time",
        )
        Session.objects.filter(profile=profile).delete()
        order = 0
        for block in preview["blocks"]:
            if block["kind"] != "lesson":
                continue
            order += 1
            Session.objects.create(
                profile=profile,
                name=block["label"].upper(),
                start_time=minutes_to_time(block["start"]),
                duration_minutes=block["end"] - block["start"],
                order=order,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("curriculum", "0023_exam_session_duration"),
    ]

    operations = [
        migrations.AddField(
            model_name="examscheduleprofile",
            name="first_exam_start_time",
            field=models.TimeField(
                default=datetime.time(8, 0),
                verbose_name="first exam starts at",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="examscheduleprofile",
            name="last_exam_end_time",
            field=models.TimeField(
                default=datetime.time(16, 0),
                verbose_name="exam end time",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="examscheduleprofile",
            name="exam_session_duration_minutes",
            field=models.PositiveIntegerField(
                default=120,
                verbose_name="exam session duration (minutes)",
            ),
        ),
        migrations.CreateModel(
            name="ExamScheduleActivity",
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
                ("start_time", models.TimeField()),
                ("duration_minutes", models.PositiveIntegerField()),
                ("order", models.PositiveIntegerField(default=0)),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="activities",
                        to="curriculum.examscheduleprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "exam schedule activity",
                "verbose_name_plural": "exam schedule activities",
                "ordering": ["start_time", "order", "name"],
            },
        ),
        migrations.RunPython(seed_exam_day_times, migrations.RunPython.noop),
    ]
