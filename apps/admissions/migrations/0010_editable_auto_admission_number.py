from django.db import migrations, models


def enable_auto_generate(apps, schema_editor):
    AdmissionSettings = apps.get_model("admissions", "AdmissionSettings")
    Student = apps.get_model("admissions", "Student")
    highest = 0
    for value in Student.objects.exclude(admission_number__isnull=True).exclude(
        admission_number=""
    ).values_list("admission_number", flat=True):
        text = str(value).strip()
        digits = ""
        for char in reversed(text):
            if char.isdigit():
                digits = char + digits
            elif digits:
                break
        if digits:
            highest = max(highest, int(digits))
        elif text.isdigit():
            highest = max(highest, int(text))
    next_number = highest + 1 if highest else 1
    obj, created = AdmissionSettings.objects.get_or_create(
        pk=1,
        defaults={
            "auto_generate_admission_number": True,
            "admission_number_next": next_number,
        },
    )
    if not created:
        updates = {"auto_generate_admission_number": True}
        if not obj.admission_number_next or obj.admission_number_next < next_number:
            updates["admission_number_next"] = next_number
        AdmissionSettings.objects.filter(pk=obj.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0009_admission_number_format"),
    ]

    operations = [
        migrations.AlterField(
            model_name="admissionsettings",
            name="auto_generate_admission_number",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "When on, the admit form suggests the next admission number. "
                    "Staff can edit the suggested value before saving."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="admissionsettings",
            name="admission_number_next",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Numeric part of the next admission number suggested on the admit form.",
            ),
        ),
        migrations.RunPython(enable_auto_generate, migrations.RunPython.noop),
    ]
