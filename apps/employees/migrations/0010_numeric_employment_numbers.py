from django.db import migrations, models


def convert_employment_numbers(apps, schema_editor):
    Employee = apps.get_model("employees", "Employee")
    IssuedEmploymentNumber = apps.get_model("employees", "IssuedEmploymentNumber")
    used = set()
    next_number = 1
    for employee in Employee.objects.order_by("id"):
        value = str(employee.employment_number or "").strip().upper()
        number = None
        if value.startswith("EMP") and value[3:].isdigit():
            number = int(value[3:])
        elif value.isdigit():
            number = int(value)
        if number is None or number < 1 or number in used:
            while next_number in used:
                next_number += 1
            number = next_number
            next_number += 1
        used.add(number)
        employee.employment_number = str(number)
        employee.save(update_fields=["employment_number"])
        IssuedEmploymentNumber.objects.get_or_create(number=number)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0009_employee_employment_number"),
    ]

    operations = [
        migrations.CreateModel(
            name="IssuedEmploymentNumber",
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
                ("number", models.PositiveIntegerField(unique=True)),
            ],
            options={
                "ordering": ["number"],
            },
        ),
        migrations.RunPython(convert_employment_numbers, noop),
        migrations.AlterField(
            model_name="employee",
            name="employment_number",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Whole number starting from 1. Assigned automatically on registration and can be edited, but never reused.",
                null=True,
                unique=True,
            ),
        ),
    ]
