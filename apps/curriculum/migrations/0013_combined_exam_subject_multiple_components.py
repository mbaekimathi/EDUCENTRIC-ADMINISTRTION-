import django.db.models.deletion
from django.db import migrations, models


def copy_pair_components(apps, schema_editor):
    CombinedExamSubject = apps.get_model("curriculum", "CombinedExamSubject")
    CombinedExamSubjectComponent = apps.get_model("curriculum", "CombinedExamSubjectComponent")

    components = []
    for combined in CombinedExamSubject.objects.all():
        components.append(
            CombinedExamSubjectComponent(
                combined_subject_id=combined.id,
                subject_setting_id=combined.first_subject_id,
                position=1,
            )
        )
        components.append(
            CombinedExamSubjectComponent(
                combined_subject_id=combined.id,
                subject_setting_id=combined.second_subject_id,
                position=2,
            )
        )
    if components:
        CombinedExamSubjectComponent.objects.bulk_create(components)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("curriculum", "0012_examsubjectsetting_display_order"),
    ]

    operations = [
        migrations.CreateModel(
            name="CombinedExamSubjectComponent",
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
                ("position", models.PositiveIntegerField(default=0)),
                (
                    "combined_subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="components",
                        to="curriculum.combinedexamsubject",
                    ),
                ),
                (
                    "subject_setting",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="combined_components",
                        to="curriculum.examsubjectsetting",
                    ),
                ),
            ],
            options={
                "verbose_name": "combined exam subject component",
                "verbose_name_plural": "combined exam subject components",
                "ordering": ["position", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="combinedexamsubjectcomponent",
            constraint=models.UniqueConstraint(
                fields=("combined_subject", "subject_setting"),
                name="unique_component_per_combined_exam_subject",
            ),
        ),
        migrations.AddField(
            model_name="combinedexamsubject",
            name="subjects",
            field=models.ManyToManyField(
                related_name="combined_subjects",
                through="curriculum.CombinedExamSubjectComponent",
                to="curriculum.examsubjectsetting",
            ),
        ),
        migrations.RunPython(copy_pair_components, noop_reverse),
        migrations.RemoveConstraint(
            model_name="combinedexamsubject",
            name="combined_exam_subjects_must_differ",
        ),
        migrations.RemoveField(
            model_name="combinedexamsubject",
            name="first_subject",
        ),
        migrations.RemoveField(
            model_name="combinedexamsubject",
            name="second_subject",
        ),
    ]
