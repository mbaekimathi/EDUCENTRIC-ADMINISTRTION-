from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0007_schoolprofile_academic_year_end_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="is_suspended",
            field=models.BooleanField(
                default=False,
                help_text="Suspended employees cannot log in, even if they are approved.",
            ),
        ),
    ]
