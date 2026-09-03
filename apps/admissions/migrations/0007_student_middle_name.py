# Generated manually for middle_name support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0006_student_assessment_number_optional"),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="middle_name",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AlterModelOptions(
            name="student",
            options={"ordering": ["last_name", "first_name", "middle_name"]},
        ),
    ]
