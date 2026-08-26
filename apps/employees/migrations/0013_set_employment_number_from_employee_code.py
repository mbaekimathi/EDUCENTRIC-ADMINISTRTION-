from django.db import migrations


def set_employment_number_from_employee_code(apps, schema_editor):
    """Set employment_number from the 6-digit employee_code.

    Login stays on employee_code. Employment number becomes that same
    numeric value (e.g. code 405081 -> employment number 405081).
    """
    Employee = apps.get_model("employees", "Employee")
    IssuedEmploymentNumber = apps.get_model("employees", "IssuedEmploymentNumber")

    rows = list(
        Employee.objects.order_by("id").values_list("id", "employee_code", "employment_number")
    )
    if not rows:
        return

    # Clear numbers first to avoid unique collisions while updating.
    Employee.objects.all().update(employment_number=None)

    used = set()
    next_free = 1
    updates = []

    for pk, code, _old_number in rows:
        code = (code or "").strip()
        if code.isdigit() and int(code) >= 1:
            number = int(code)
        else:
            while next_free in used:
                next_free += 1
            number = next_free
            next_free += 1

        if number in used:
            while next_free in used:
                next_free += 1
            number = next_free
            next_free += 1

        used.add(number)
        updates.append((pk, number))

    for pk, number in updates:
        Employee.objects.filter(pk=pk).update(employment_number=number)

    IssuedEmploymentNumber.objects.all().delete()
    IssuedEmploymentNumber.objects.bulk_create(
        [IssuedEmploymentNumber(number=number) for number in sorted(used)]
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0012_employee_title_tr"),
    ]

    operations = [
        migrations.RunPython(set_employment_number_from_employee_code, noop_reverse),
    ]
