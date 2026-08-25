from django.db import migrations, models


def fill_duration_from_end_time(apps, schema_editor):
    Session = apps.get_model("curriculum", "ExamTimetableSession")
    for session in Session.objects.all():
        start = session.start_time.hour * 60 + session.start_time.minute
        end = session.end_time.hour * 60 + session.end_time.minute
        session.duration_minutes = max(end - start, 1)
        session.save(update_fields=["duration_minutes"])


class Migration(migrations.Migration):

    dependencies = [
        ("curriculum", "0022_exam_schedule_profiles"),
    ]

    operations = [
        migrations.AddField(
            model_name="examtimetablesession",
            name="duration_minutes",
            field=models.PositiveIntegerField(default=60),
            preserve_default=False,
        ),
        migrations.RunPython(fill_duration_from_end_time, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="examtimetablesession",
            name="end_time",
        ),
    ]
