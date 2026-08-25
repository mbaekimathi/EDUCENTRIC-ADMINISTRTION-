import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0003_learning_area"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="learningarea",
                    old_name="education_level",
                    new_name="academic_level",
                ),
                migrations.AlterField(
                    model_name="learningarea",
                    name="academic_level",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="learning_areas",
                        to="curriculum.academiclevel",
                        verbose_name="academic level",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE `curriculum_learningarea` "
                        "CHANGE `education_level_id` `academic_level_id` bigint(20) NOT NULL"
                    ),
                    reverse_sql=(
                        "ALTER TABLE `curriculum_learningarea` "
                        "CHANGE `academic_level_id` `education_level_id` bigint(20) NOT NULL"
                    ),
                ),
            ],
        ),
    ]
