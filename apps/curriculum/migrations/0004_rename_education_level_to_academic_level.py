import django.db.models.deletion
from django.db import migrations, models


def _learning_area_level_columns(connection):
    table = "curriculum_learningarea"
    with connection.cursor() as cursor:
        if connection.vendor == "mysql":
            cursor.execute(
                """
                SELECT COLUMN_NAME FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                """,
                [table],
            )
            return {row[0] for row in cursor.fetchall()}
        if connection.vendor == "sqlite":
            cursor.execute(f"PRAGMA table_info({table})")
            return {row[1] for row in cursor.fetchall()}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = %s
            """,
            [table],
        )
        return {row[0] for row in cursor.fetchall()}


def _rename_learning_area_level_column(schema_editor, *, to_academic: bool):
    connection = schema_editor.connection
    table = "curriculum_learningarea"
    old_col = "education_level_id" if to_academic else "academic_level_id"
    new_col = "academic_level_id" if to_academic else "education_level_id"

    columns = _learning_area_level_columns(connection)
    if old_col not in columns:
        return

    if connection.vendor == "mysql":
        schema_editor.execute(
            f"ALTER TABLE `{table}` "
            f"CHANGE `{old_col}` `{new_col}` bigint(20) NOT NULL"
        )
        return

    if connection.vendor == "sqlite":
        schema_editor.execute(
            f"ALTER TABLE {table} RENAME COLUMN {old_col} TO {new_col}"
        )
        return

    schema_editor.execute(
        f"ALTER TABLE {table} RENAME COLUMN {old_col} TO {new_col}"
    )


def rename_to_academic_level(apps, schema_editor):
    _rename_learning_area_level_column(schema_editor, to_academic=True)


def rename_to_education_level(apps, schema_editor):
    _rename_learning_area_level_column(schema_editor, to_academic=False)


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
                migrations.RunPython(
                    rename_to_academic_level,
                    rename_to_education_level,
                ),
            ],
        ),
    ]
