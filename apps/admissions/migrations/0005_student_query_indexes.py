from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("admissions", "0004_student_profile_image"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="student",
            index=models.Index(fields=["academic_level"], name="student_academic_level_idx"),
        ),
        migrations.AddIndex(
            model_name="student",
            index=models.Index(fields=["class_group"], name="student_class_group_idx"),
        ),
        migrations.AddIndex(
            model_name="student",
            index=models.Index(
                fields=["academic_level", "class_group"],
                name="student_level_class_idx",
            ),
        ),
    ]
