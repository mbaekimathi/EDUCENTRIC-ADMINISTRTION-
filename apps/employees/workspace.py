from .models import Employee

WORKSPACE_ROLE_SESSION_KEY = "workspace_role"
WORKSPACE_VIEW_EMPLOYEE_SESSION_KEY = "workspace_view_employee_id"
ACTIVE_WORKSPACE_ROLE_SESSION_KEY = "active_workspace_role"


def _valid_roles():
    return {value for value, _label in Employee.Role.choices}


def user_role_values(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    if hasattr(user, "role_values"):
        return user.role_values()
    role = getattr(user, "role", None)
    return [role] if role else []


def prefetch_user_roles(user):
    """Warm the per-instance role cache for the authenticated user."""
    if user is not None and getattr(user, "is_authenticated", False) and hasattr(user, "role_values"):
        user.role_values()


def can_switch_workspace_role(user):
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and (
            user.has_role(Employee.Role.IT_SUPPORT)
            if hasattr(user, "has_role")
            else user.role == Employee.Role.IT_SUPPORT
        )
    )


def can_choose_own_workspace_role(user):
    return len(user_role_values(user)) > 1


def set_active_workspace_role(request, role):
    role = (role or "").upper()
    if role not in user_role_values(request.user):
        return False
    request.session[ACTIVE_WORKSPACE_ROLE_SESSION_KEY] = role
    return True


def clear_active_workspace_role(request):
    request.session.pop(ACTIVE_WORKSPACE_ROLE_SESSION_KEY, None)


def is_workspace_preview(request):
    user = getattr(request, "user", None)
    if not can_switch_workspace_role(user):
        return False
    employee_id = request.session.get(WORKSPACE_VIEW_EMPLOYEE_SESSION_KEY)
    viewing = request.session.get(WORKSPACE_ROLE_SESSION_KEY)
    if not employee_id or viewing not in _valid_roles():
        return False
    return employee_id != user.pk or viewing not in user_role_values(user)


def needs_login_role_selection(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return False
    roles = user_role_values(user)
    if len(roles) <= 1:
        if roles and not request.session.get(ACTIVE_WORKSPACE_ROLE_SESSION_KEY):
            request.session[ACTIVE_WORKSPACE_ROLE_SESSION_KEY] = roles[0]
        return False
    if is_workspace_preview(request):
        return False
    active = request.session.get(ACTIVE_WORKSPACE_ROLE_SESSION_KEY)
    return active not in roles


def workspace_role(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None

    roles = user_role_values(user)

    if can_switch_workspace_role(user):
        viewing = request.session.get(WORKSPACE_ROLE_SESSION_KEY)
        employee_id = request.session.get(WORKSPACE_VIEW_EMPLOYEE_SESSION_KEY)
        if employee_id and viewing in _valid_roles():
            return viewing
        if viewing in roles:
            return viewing

    active = request.session.get(ACTIVE_WORKSPACE_ROLE_SESSION_KEY)
    if active in roles:
        return active

    return user.role if user.role in roles else (roles[0] if roles else user.role)


def workspace_role_label(role):
    return dict(Employee.Role.choices).get(role, "")


def uses_profile_settings(role):
    return role == Employee.Role.TEACHER


def employees_for_workspace_role(role):
    return (
        Employee.objects.filter(
            assigned_roles__role=role,
            approval_status=Employee.ApprovalStatus.APPROVED,
            is_active=True,
            is_suspended=False,
        )
        .distinct()
        .order_by("last_name", "first_name", "employee_code")
    )


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


def exam_management_url_names(role=None):
    """Named URL map for assessment management (IT Support + Secretary)."""
    if role == Employee.Role.SECRETARY:
        return {
            "exam_hub_url": "employees:secretary_assessment_management",
            "exam_hub_section": None,
            "exam_page_url": "employees:secretary_exam_page",
            "exam_record_detail_url": "employees:secretary_exam_record_detail",
            "exam_record_level_url": "employees:secretary_exam_record_level",
            "exam_manual_allocation_url": "employees:secretary_exam_manual_supervisor_allocation",
            "update_exam_record_url": "employees:secretary_update_exam_record",
            "update_exam_record_status_url": "employees:secretary_update_exam_record_status",
            "set_current_exam_record_url": "employees:secretary_set_current_exam_record",
            "update_exam_record_deadline_url": "employees:secretary_update_exam_record_deadline",
            "delete_exam_record_url": "employees:secretary_delete_exam_record",
        }
    return {
        "exam_hub_url": "employees:it_support_curriculum_section",
        "exam_hub_section": "exam-management",
        "exam_page_url": "employees:it_support_exam_page",
        "exam_record_detail_url": "employees:exam_record_detail",
        "exam_record_level_url": "employees:exam_record_level",
        "exam_manual_allocation_url": "employees:exam_manual_supervisor_allocation",
        "update_exam_record_url": "employees:update_exam_record",
        "update_exam_record_status_url": "employees:update_exam_record_status",
        "set_current_exam_record_url": "employees:set_current_exam_record",
        "update_exam_record_deadline_url": "employees:update_exam_record_deadline",
        "delete_exam_record_url": "employees:delete_exam_record",
    }
