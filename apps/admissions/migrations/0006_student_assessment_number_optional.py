# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0005_student_query_indexes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="student",
            name="assessment_number",
            field=models.CharField(blank=True, max_length=50, null=True, unique=True),
        ),
    ]
