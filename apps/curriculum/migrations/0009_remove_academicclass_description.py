from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0008_academicclass"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="academicclass",
            name="description",
        ),
    ]
