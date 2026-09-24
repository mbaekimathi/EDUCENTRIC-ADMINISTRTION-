from django.db import migrations, models


def _grade_band_table(apps):
    return apps.get_model("curriculum", "GradeBand")._meta.db_table


def _existing_indexes(schema_editor, table):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        if connection.vendor in ("mysql", "mariadb"):
            cursor.execute(f"SHOW INDEX FROM `{table}`")
            return {row[2] for row in cursor.fetchall()}
        if connection.vendor == "sqlite":
            cursor.execute(f"PRAGMA index_list({table})")
            return {row[1] for row in cursor.fetchall()}
    return set()


def apply_grade_band_unique(apps, schema_editor):
    table = _grade_band_table(apps)
    indexes = _existing_indexes(schema_editor, table)
    for old_name in ("unique_default_grade_band_code", "unique_level_grade_band_code"):
        if old_name not in indexes:
            continue
        schema_editor.execute(f"ALTER TABLE `{table}` DROP INDEX `{old_name}`")
    new_name = "unique_grade_band_code_per_level"
    if new_name in _existing_indexes(schema_editor, table):
        return
    schema_editor.execute(
        f"ALTER TABLE `{table}` ADD CONSTRAINT `{new_name}` "
        "UNIQUE (`academic_level_id`, `code`)"
    )


def reverse_grade_band_unique(apps, schema_editor):
    table = _grade_band_table(apps)
    indexes = _existing_indexes(schema_editor, table)
    new_name = "unique_grade_band_code_per_level"
    if new_name in indexes:
        schema_editor.execute(f"ALTER TABLE `{table}` DROP INDEX `{new_name}`")


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0046_alter_combinedexamsubject_options_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="gradeband",
                    name="unique_default_grade_band_code",
                ),
                migrations.RemoveConstraint(
                    model_name="gradeband",
                    name="unique_level_grade_band_code",
                ),
                migrations.AddConstraint(
                    model_name="gradeband",
                    constraint=models.UniqueConstraint(
                        fields=("academic_level", "code"),
                        name="unique_grade_band_code_per_level",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(
                    apply_grade_band_unique,
                    reverse_grade_band_unique,
                ),
            ],
        ),
    ]
