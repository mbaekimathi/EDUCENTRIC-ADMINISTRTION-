from .models import Employee

WORKSPACE_ROLE_SESSION_KEY = "workspace_role"
WORKSPACE_VIEW_EMPLOYEE_SESSION_KEY = "workspace_view_employee_id"


def _valid_roles():
    return {value for value, _label in Employee.Role.choices}


def can_switch_workspace_role(user):
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and user.role == Employee.Role.IT_SUPPORT
    )


def workspace_role(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    if not can_switch_workspace_role(user):
        return user.role
    viewing = request.session.get(WORKSPACE_ROLE_SESSION_KEY)
    if viewing in _valid_roles():
        return viewing
    return user.role


def workspace_role_label(role):
    return dict(Employee.Role.choices).get(role, "")


def employees_for_workspace_role(role):
    return Employee.objects.filter(
        role=role,
        approval_status=Employee.ApprovalStatus.APPROVED,
        is_active=True,
        is_suspended=False,
    ).order_by("last_name", "first_name", "employee_code")


def workspace_view_employee(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    if not can_switch_workspace_role(user):
        return user
    employee_id = request.session.get(WORKSPACE_VIEW_EMPLOYEE_SESSION_KEY)
    if not employee_id:
        return user
    employee = employees_for_workspace_role(workspace_role(request)).filter(pk=employee_id).first()
    return employee or user


def clear_workspace_preview(request):
    request.session.pop(WORKSPACE_ROLE_SESSION_KEY, None)
    request.session.pop(WORKSPACE_VIEW_EMPLOYEE_SESSION_KEY, None)
