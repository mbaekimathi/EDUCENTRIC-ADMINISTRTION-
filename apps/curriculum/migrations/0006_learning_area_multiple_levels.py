import django.db.models.deletion
from django.db import migrations, models


def _table_has_column(connection, table, column):
    with connection.cursor() as cursor:
        if connection.vendor == "mysql":
            cursor.execute(
                """
                SELECT 1 FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = %s
                  AND COLUMN_NAME = %s
                LIMIT 1
                """,
                [table, column],
            )
            return cursor.fetchone() is not None
        if connection.vendor == "sqlite":
            cursor.execute(f"PRAGMA table_info({table})")
            return column in {row[1] for row in cursor.fetchall()}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            LIMIT 1
            """,
            [table, column],
        )
        return cursor.fetchone() is not None


def copy_levels_to_m2m(apps, schema_editor):
    connection = schema_editor.connection
    if not _table_has_column(connection, "curriculum_learningarea", "academic_level_id"):
        return
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


def _mysql_index_exists(connection, table, index_name):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1 FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
              AND INDEX_NAME = %s
            LIMIT 1
            """,
            [table, index_name],
        )
        return cursor.fetchone() is not None


def drop_level_code_unique(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor == "mysql":
        if not _mysql_index_exists(
            connection, "curriculum_learningarea", "unique_learning_area_code_per_level"
        ):
            return
        schema_editor.execute(
            "ALTER TABLE `curriculum_learningarea` "
            "DROP INDEX `unique_learning_area_code_per_level`"
        )
        return
    if connection.vendor == "sqlite":
        schema_editor.execute(
            "DROP INDEX IF EXISTS unique_learning_area_code_per_level"
        )
        return
    schema_editor.execute(
        "ALTER TABLE curriculum_learningarea "
        "DROP CONSTRAINT IF EXISTS unique_learning_area_code_per_level"
    )


def add_academic_levels_m2m_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    through_table = "curriculum_learningarea_academic_levels"
    with connection.cursor() as cursor:
        if connection.vendor == "mysql":
            cursor.execute(
                """
                SELECT 1 FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                LIMIT 1
                """,
                [through_table],
            )
            if cursor.fetchone():
                return
        elif connection.vendor == "sqlite":
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=%s",
                [through_table],
            )
            if cursor.fetchone():
                return
    LearningArea = apps.get_model("curriculum", "LearningArea")
    field = LearningArea._meta.get_field("academic_levels")
    schema_editor.create_model(field.remote_field.through)


def ensure_learning_area_code_unique(apps, schema_editor):
    connection = schema_editor.connection
    table = "curriculum_learningarea"
    column = "code"
    if connection.vendor == "mysql":
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT INDEX_NAME, NON_UNIQUE FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = %s
                  AND COLUMN_NAME = %s
                """,
                [table, column],
            )
            for _name, non_unique in cursor.fetchall():
                if non_unique == 0:
                    return
        schema_editor.execute(
            f"ALTER TABLE `{table}` ADD UNIQUE (`{column}`)"
        )
        return
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute(f"PRAGMA index_list({table})")
            for row in cursor.fetchall():
                if row[2]:  # unique
                    cursor.execute(f"PRAGMA index_info({row[1]})")
                    cols = [r[2] for r in cursor.fetchall()]
                    if cols == [column]:
                        return
        schema_editor.execute(
            f"CREATE UNIQUE INDEX curriculum_learningarea_code_uniq ON {table} ({column})"
        )


def remove_academic_level_fk_if_present(apps, schema_editor):
    connection = schema_editor.connection
    table = "curriculum_learningarea"
    column = "academic_level_id"
    if not _table_has_column(connection, table, column):
        return
    schema_editor.execute(f"ALTER TABLE `{table}` DROP COLUMN `{column}`")


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
                migrations.RunPython(drop_level_code_unique, noop_reverse),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="learningarea",
                    name="academic_levels",
                    field=models.ManyToManyField(
                        related_name="learning_areas",
                        to="curriculum.academiclevel",
                        verbose_name="academic levels",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_academic_levels_m2m_if_missing, noop_reverse),
            ],
        ),
        migrations.RunPython(copy_levels_to_m2m, noop_reverse),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="learningarea",
                    name="academic_level",
                ),
            ],
            database_operations=[
                migrations.RunPython(remove_academic_level_fk_if_present, noop_reverse),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="learningarea",
                    name="code",
                    field=models.CharField(max_length=40, unique=True),
                ),
            ],
            database_operations=[
                migrations.RunPython(ensure_learning_area_code_unique, noop_reverse),
            ],
        ),
    ]
