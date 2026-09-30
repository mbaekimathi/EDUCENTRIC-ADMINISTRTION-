from django.db import migrations


def expand_legacy_permissions(apps, schema_editor):
    Employee = apps.get_model("employees", "Employee")
    EmployeeRole = apps.get_model("employees", "EmployeeRole")
    EmployeeActivityPermission = apps.get_model("employees", "EmployeeActivityPermission")
    from apps.employees.permissions import activity_codes_for_role, modules_for_role

    approved = Employee.objects.filter(approval_status="APPROVED")
    for employee in approved.iterator():
        roles = list(
            EmployeeRole.objects.filter(employee_id=employee.pk).values_list(
                "role", flat=True
            )
        )
        if not roles and employee.role:
            roles = [employee.role]
        for role in roles:
            existing = {
                row.activity_code: row.is_enabled
                for row in EmployeeActivityPermission.objects.filter(
                    employee_id=employee.pk,
                    role=role,
                )
            }
            for module_def in modules_for_role(role):
                base = module_def["code"]
                base_enabled = existing.get(base, True)
                for action in module_def["actions"]:
                    code = f"{base}.{action}"
                    if code in existing:
                        continue
                    EmployeeActivityPermission.objects.get_or_create(
                        employee_id=employee.pk,
                        role=role,
                        activity_code=code,
                        defaults={"is_enabled": base_enabled},
                    )
            # Remove legacy module-only rows once action rows exist.
            legacy_codes = {module_def["code"] for module_def in modules_for_role(role)}
            action_codes = set(activity_codes_for_role(role))
            EmployeeActivityPermission.objects.filter(
                employee_id=employee.pk,
                role=role,
                activity_code__in=legacy_codes - action_codes,
            ).delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0018_publish_existing_school_activities"),
    ]

    operations = [
        migrations.RunPython(expand_legacy_permissions, noop_reverse),
    ]
