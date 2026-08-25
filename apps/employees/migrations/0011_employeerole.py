from django.db import migrations, models
import django.db.models.deletion


def backfill_employee_roles(apps, schema_editor):
    Employee = apps.get_model("employees", "Employee")
    EmployeeRole = apps.get_model("employees", "EmployeeRole")
    rows = []
    for employee in Employee.objects.exclude(role="").iterator():
        rows.append(EmployeeRole(employee_id=employee.pk, role=employee.role))
        if len(rows) >= 500:
            EmployeeRole.objects.bulk_create(rows, ignore_conflicts=True)
            rows = []
    if rows:
        EmployeeRole.objects.bulk_create(rows, ignore_conflicts=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0010_numeric_employment_numbers"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmployeeRole",
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
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("EMPLOYEE", "Employee"),
                            ("HEAD_OF_INSTITUTION", "Head of Institution"),
                            ("DEPUTY_HEAD_OF_INSTITUTION", "Deputy Head of Institution"),
                            ("CURRICULUM_COORDINATOR", "Curriculum Coordinator"),
                            ("TEACHER", "Teacher"),
                            ("ACCOUNTANT", "Accountant"),
                            ("LIBRARIAN", "Librarian"),
                            ("STORE_MANAGER", "Store Manager"),
                            ("WARDEN", "Warden"),
                            ("SECRETARY", "Secretary"),
                            ("IT_SUPPORT", "IT Support"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assigned_roles",
                        to="employees.employee",
                    ),
                ),
            ],
            options={
                "verbose_name": "employee role",
                "verbose_name_plural": "employee roles",
                "ordering": ["role"],
            },
        ),
        migrations.AddConstraint(
            model_name="employeerole",
            constraint=models.UniqueConstraint(
                fields=("employee", "role"),
                name="unique_employee_role_assignment",
            ),
        ),
        migrations.RunPython(backfill_employee_roles, noop_reverse),
    ]
