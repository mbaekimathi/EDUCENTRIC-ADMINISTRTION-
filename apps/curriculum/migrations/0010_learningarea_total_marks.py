from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0009_remove_academicclass_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="learningarea",
            name="total_marks",
            field=models.DecimalField(
                decimal_places=2,
                default=100,
                max_digits=7,
                verbose_name="total marks",
            ),
        ),
    ]
