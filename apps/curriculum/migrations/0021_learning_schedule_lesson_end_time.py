import datetime

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("curriculum", "0020_learning_schedule_profiles"),
    ]

    operations = [
        migrations.AddField(
            model_name="learningscheduleprofile",
            name="last_class_end_time",
            field=models.TimeField(
                default=datetime.time(16, 0),
                verbose_name="lesson end time",
            ),
            preserve_default=False,
        ),
    ]
