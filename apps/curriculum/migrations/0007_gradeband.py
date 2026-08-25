from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0006_learning_area_multiple_levels"),
    ]

    operations = [
        migrations.CreateModel(
            name="GradeBand",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("minimum_score", models.DecimalField(decimal_places=2, max_digits=5, verbose_name="minimum score")),
                ("maximum_score", models.DecimalField(decimal_places=2, max_digits=5, verbose_name="maximum score")),
                ("grade", models.CharField(max_length=20)),
                ("description", models.CharField(blank=True, max_length=160)),
                (
                    "learning_area",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="grade_bands",
                        to="curriculum.learningarea",
                        verbose_name="learning area",
                    ),
                ),
            ],
            options={
                "verbose_name": "grade band",
                "verbose_name_plural": "grade bands",
                "ordering": ["learning_area__name", "-maximum_score", "-minimum_score", "grade"],
            },
        ),
        migrations.AddConstraint(
            model_name="gradeband",
            constraint=models.UniqueConstraint(
                fields=("learning_area", "minimum_score", "maximum_score"),
                name="unique_grade_band_range_per_learning_area",
            ),
        ),
        migrations.AddConstraint(
            model_name="gradeband",
            constraint=models.UniqueConstraint(
                fields=("learning_area", "grade"),
                name="unique_grade_per_learning_area",
            ),
        ),
    ]
