from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0010_editable_auto_admission_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="clearance_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("TRANSFER", "Transfer to another school"),
                    ("COMPLETED_SCHOOL", "Completed school"),
                ],
                help_text="Reason recorded when the student was cleared.",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="student",
            name="cleared_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="student",
            name="enrollment_status",
            field=models.CharField(
                choices=[
                    ("ACTIVE", "Active"),
                    ("TRANSFER", "Transfer"),
                    ("ALUMNAE", "Alumnae"),
                ],
                default="ACTIVE",
                help_text="School enrollment status: active, transfer, or alumnae.",
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="student",
            index=models.Index(
                fields=["enrollment_status"],
                name="student_enrollment_status_idx",
            ),
        ),
    ]
