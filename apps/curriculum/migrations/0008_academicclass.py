from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0007_gradeband"),
    ]

    operations = [
        migrations.CreateModel(
            name="AcademicClass",
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
                ("name", models.CharField(max_length=120, verbose_name="class name")),
                ("code", models.CharField(max_length=40, verbose_name="class code")),
                ("description", models.TextField(blank=True)),
                ("order", models.PositiveIntegerField(default=0, verbose_name="class order")),
                (
                    "status",
                    models.CharField(
                        choices=[("ACTIVE", "ACTIVE"), ("INACTIVE", "INACTIVE")],
                        default="ACTIVE",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "academic_level",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="classes",
                        to="curriculum.academiclevel",
                        verbose_name="academic level",
                    ),
                ),
            ],
            options={
                "verbose_name": "academic class",
                "verbose_name_plural": "academic classes",
                "ordering": ["academic_level", "order", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="academicclass",
            constraint=models.UniqueConstraint(
                fields=("academic_level", "code"),
                name="unique_class_code_per_academic_level",
            ),
        ),
    ]
