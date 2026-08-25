import django.db.models.deletion
from django.db import migrations, models


def copy_levels_to_m2m(apps, schema_editor):
    LearningArea = apps.get_model("curriculum", "LearningArea")
    through = LearningArea.academic_levels.through
    for area in LearningArea.objects.all():
        level_id = getattr(area, "academic_level_id", None)
        if level_id:
            through.objects.get_or_create(
                learningarea_id=area.id,
                academiclevel_id=level_id,
            )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0005_category_as_text_input"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="learningarea",
                    name="unique_learning_area_code_per_level",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE `curriculum_learningarea` "
                        "DROP INDEX `unique_learning_area_code_per_level`"
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        migrations.AddField(
            model_name="learningarea",
            name="academic_levels",
            field=models.ManyToManyField(
                related_name="learning_areas",
                to="curriculum.academiclevel",
                verbose_name="academic levels",
            ),
        ),
        migrations.RunPython(copy_levels_to_m2m, noop_reverse),
        migrations.RemoveField(
            model_name="learningarea",
            name="academic_level",
        ),
        migrations.AlterField(
            model_name="learningarea",
            name="code",
            field=models.CharField(max_length=40, unique=True),
        ),
    ]
