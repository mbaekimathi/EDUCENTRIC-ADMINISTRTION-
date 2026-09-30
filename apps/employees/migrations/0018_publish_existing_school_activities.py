# Generated manually for existing school activities.

from django.db import migrations


def publish_existing_activities(apps, schema_editor):
    SchoolActivity = apps.get_model("employees", "SchoolActivity")
    SchoolActivity.objects.filter(status="DRAFT").update(status="PUBLISHED")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0017_school_activity_status"),
    ]

    operations = [
        migrations.RunPython(publish_existing_activities, noop_reverse),
    ]
