# Generated manually for parent portal profile photos.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0011_student_enrollment_clearance"),
    ]

    operations = [
        migrations.AddField(
            model_name="parentguardian",
            name="profile_image",
            field=models.ImageField(blank=True, upload_to="parents/profiles/"),
        ),
    ]
