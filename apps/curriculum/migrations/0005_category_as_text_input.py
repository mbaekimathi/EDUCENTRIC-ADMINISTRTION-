from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0004_rename_education_level_to_academic_level"),
    ]

    operations = [
        migrations.AlterField(
            model_name="academiclevel",
            name="category",
            field=models.CharField(max_length=120, verbose_name="level category"),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="learningarea",
                    name="unique_learning_area_code_per_level",
                ),
                migrations.AddConstraint(
                    model_name="learningarea",
                    constraint=models.UniqueConstraint(
                        fields=("academic_level", "code"),
                        name="unique_learning_area_code_per_level",
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
