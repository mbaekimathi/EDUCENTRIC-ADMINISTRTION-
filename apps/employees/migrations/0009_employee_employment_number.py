from django.db import migrations, models


def assign_employment_numbers(apps, schema_editor):
    Employee = apps.get_model("employees", "Employee")
    for index, employee in enumerate(Employee.objects.order_by("id"), start=1):
        employee.employment_number = f"EMP{index:04d}"
        employee.save(update_fields=["employment_number"])


def clear_employment_numbers(apps, schema_editor):
    Employee = apps.get_model("employees", "Employee")
    Employee.objects.update(employment_number="")


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0008_employee_is_suspended"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="employment_number",
            field=models.CharField(
                default="",
                help_text="School employment number. Assigned automatically on registration and can be edited.",
                max_length=32,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(assign_employment_numbers, clear_employment_numbers),
        migrations.AlterField(
            model_name="employee",
            name="employment_number",
            field=models.CharField(
                blank=True,
                help_text="School employment number. Assigned automatically on registration and can be edited.",
                max_length=32,
                unique=True,
            ),
        ),
    ]
