from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0043_generated_exam_timetable_status_deadline"),
    ]

    operations = [
        migrations.AlterField(
            model_name="generatedexamsitting",
            name="supervisor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="generated_exam_sittings",
                to="employees.employee",
            ),
        ),
    ]
