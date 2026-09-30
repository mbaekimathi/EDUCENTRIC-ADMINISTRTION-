"""Role module permissions with per-action toggles (view, edit, delete, …)."""

from __future__ import annotations

from collections import OrderedDict

from django.core.cache import cache
from django.db import transaction

from .models import Employee, EmployeeActivityPermission

_PERMISSION_CACHE_TTL = 120


def _permission_cache_key(employee_id, role, activity_code):
    return f"emp_perm:{employee_id}:{role}:{activity_code}"


def invalidate_employee_permission_cache(employee_id, role=None):
    """Drop cached permission checks for an employee (all roles or one role)."""
    if not employee_id:
        return
    # LocMem/Redis do not support wildcard delete reliably without keys();
    # version bump via a short-lived marker keeps lookups correct.
    if role:
        cache.set(f"emp_perm_epoch:{employee_id}:{role}", cache.get(f"emp_perm_epoch:{employee_id}:{role}", 0) + 1, 86400)
    cache.set(f"emp_perm_epoch:{employee_id}", cache.get(f"emp_perm_epoch:{employee_id}", 0) + 1, 86400)


def _permission_epoch(employee_id, role):
    global_epoch = cache.get(f"emp_perm_epoch:{employee_id}", 0) or 0
    role_epoch = cache.get(f"emp_perm_epoch:{employee_id}:{role}", 0) or 0
    return f"{global_epoch}:{role_epoch}"

ACTION_LABELS = OrderedDict(
    (
        ("view", "View"),
        ("create", "Create / register"),
        ("edit", "Edit"),
        ("delete", "Delete"),
        ("suspend", "Suspend / unsuspend"),
        ("approve", "Approve"),
        ("generate", "Generate"),
        ("download", "Download / export"),
    )
)

KNOWN_ACTIONS = frozenset(ACTION_LABELS.keys())


def _module(code, label, group, actions):
    return {
        "code": code,
        "label": label,
        "module": group,
        "actions": tuple(actions),
    }


_FULL_MODULE_DEFINITIONS = (
    _module(
        "module.human_resource_management",
        "Human resource management",
        "Human resource management",
        ("view", "edit", "delete", "suspend"),
    ),
    _module(
        "module.student_management",
        "Student management",
        "Student management",
        ("view", "edit", "delete", "suspend", "approve"),
    ),
    _module(
        "module.curriculum_management",
        "Curriculum management",
        "Curriculum management",
        ("view",),
    ),
    _module(
        "curriculum.learning_management",
        "Learning management",
        "Curriculum management",
        ("view", "edit", "delete", "suspend", "generate"),
    ),
    _module(
        "curriculum.elearning_management",
        "E-learning management",
        "Curriculum management",
        ("view", "edit", "delete", "generate", "download"),
    ),
    _module(
        "curriculum.exam_management",
        "Assessment management",
        "Curriculum management",
        ("view", "edit", "delete", "generate", "download"),
    ),
    _module(
        "module.financial_management",
        "Financial management",
        "Financial management",
        ("view", "edit", "download"),
    ),
    _module(
        "module.stock_management",
        "Stock management",
        "Stock management",
        ("view", "edit", "download"),
    ),
    _module(
        "module.reports",
        "Reports",
        "Reports",
        ("view", "download"),
    ),
    _module(
        "module.system_performance",
        "System performance",
        "System performance",
        ("view",),
    ),
    _module(
        "module.school_activities",
        "School activities",
        "School activities",
        ("view", "create", "delete"),
    ),
)

_CURRICULUM_COORDINATOR_DEFINITIONS = (
    _module(
        "module.student_management",
        "Student management",
        "Student management",
        ("view", "edit", "delete", "suspend", "approve"),
    ),
    _module(
        "module.curriculum_management",
        "Curriculum management",
        "Curriculum management",
        ("view",),
    ),
    _module(
        "curriculum.learning_management",
        "Learning management",
        "Curriculum management",
        ("view", "edit", "delete", "suspend", "generate"),
    ),
    _module(
        "curriculum.elearning_management",
        "E-learning management",
        "Curriculum management",
        ("view", "edit", "delete", "generate", "download"),
    ),
    _module(
        "curriculum.exam_management",
        "Assessment management",
        "Curriculum management",
        ("view", "edit", "delete", "generate", "download"),
    ),
    _module(
        "module.reports",
        "Reports",
        "Reports",
        ("view", "download"),
    ),
    _module(
        "module.school_activities",
        "School activities",
        "School activities",
        ("view", "create", "delete"),
    ),
)

_SECRETARY_DEFINITIONS = (
    _module(
        "module.student_management",
        "Student management",
        "Student management",
        ("view", "edit", "delete", "suspend", "approve"),
    ),
    _module(
        "module.curriculum_management",
        "Curriculum management",
        "Curriculum management",
        ("view",),
    ),
    _module(
        "curriculum.exam_management",
        "Assessment management",
        "Curriculum management",
        ("view", "edit", "delete", "generate", "download"),
    ),
    _module(
        "module.reports",
        "Reports",
        "Reports",
        ("view", "download"),
    ),
    _module(
        "module.school_activities",
        "School activities",
        "School activities",
        ("view", "create", "delete"),
    ),
)

_TEACHER_DEFINITIONS = (
    _module(
        "teacher.session_timetable",
        "Session timetable",
        "Teacher workspace",
        ("view",),
    ),
    _module(
        "teacher.my_class",
        "My class",
        "Teacher workspace",
        ("view", "create", "edit", "delete"),
    ),
    _module(
        "teacher.elearning",
        "E-learning",
        "Teacher workspace",
        ("view", "edit", "download"),
    ),
    _module(
        "teacher.subject_attendance",
        "Subject attendance",
        "Teacher workspace",
        ("view", "edit"),
    ),
    _module(
        "teacher.learning_reports",
        "Learning reports",
        "Teacher workspace",
        ("view", "download"),
    ),
    _module(
        "teacher.assessment_records",
        "Assessment records",
        "Teacher workspace",
        ("view", "edit", "download"),
    ),
)

_BASIC_WORKSPACE_DEFINITIONS = (
    _module("workspace.access", "Workspace access", "Workspace", ("view",)),
)

ROLE_MODULE_DEFINITIONS = OrderedDict(
    (
        (Employee.Role.HEAD_OF_INSTITUTION, _FULL_MODULE_DEFINITIONS),
        (Employee.Role.DEPUTY_HEAD_OF_INSTITUTION, _FULL_MODULE_DEFINITIONS),
        (Employee.Role.IT_SUPPORT, _FULL_MODULE_DEFINITIONS),
        (Employee.Role.CURRICULUM_COORDINATOR, _CURRICULUM_COORDINATOR_DEFINITIONS),
        (Employee.Role.TEACHER, _TEACHER_DEFINITIONS),
        (Employee.Role.SECRETARY, _SECRETARY_DEFINITIONS),
        (Employee.Role.ACCOUNTANT, _BASIC_WORKSPACE_DEFINITIONS),
        (Employee.Role.LIBRARIAN, _BASIC_WORKSPACE_DEFINITIONS),
        (Employee.Role.STORE_MANAGER, _BASIC_WORKSPACE_DEFINITIONS),
        (Employee.Role.WARDEN, _BASIC_WORKSPACE_DEFINITIONS),
        (Employee.Role.EMPLOYEE, _BASIC_WORKSPACE_DEFINITIONS),
    )
)

MODULE_SLUG_ACTIVITY = {
    "human-resource-management": "module.human_resource_management",
    "student-management": "module.student_management",
    "curriculum-management": "module.curriculum_management",
    "financial-management": "module.financial_management",
    "stock-management": "module.stock_management",
    "reports": "module.reports",
}

CURRICULUM_SECTION_ACTIVITY = {
    "learning-management": "curriculum.learning_management",
    "e-learning-management": "curriculum.elearning_management",
    "exam-management": "curriculum.exam_management",
}


def module_action_code(module_code, action):
    return f"{(module_code or '').strip()}.{(action or '').strip()}"


def modules_for_role(role):
    return list(ROLE_MODULE_DEFINITIONS.get(role, _BASIC_WORKSPACE_DEFINITIONS))


def expand_module_to_activities(module_def):
    """Flatten one module definition into permission rows (one per action)."""
    return [
        {
            "code": module_action_code(module_def["code"], action),
            "module": module_def["module"],
            "module_code": module_def["code"],
            "module_label": module_def["label"],
            "action": action,
            "label": ACTION_LABELS.get(action, action.replace("_", " ").title()),
        }
        for action in module_def["actions"]
    ]


def activities_for_role(role):
    activities = []
    for module_def in modules_for_role(role):
        activities.extend(expand_module_to_activities(module_def))
    return activities


def activity_codes_for_role(role):
    return [item["code"] for item in activities_for_role(role)]


def group_activities_by_module(activities):
    """Group flattened action permissions under their module for the UI."""
    grouped = OrderedDict()
    for activity in activities:
        key = activity.get("module_code") or activity["module"]
        bucket = grouped.setdefault(
            key,
            {
                "module": activity.get("module_label") or activity["module"],
                "module_code": activity.get("module_code") or key,
                "group": activity["module"],
                "activities": [],
            },
        )
        bucket["activities"].append(activity)
    return list(grouped.values())


def ensure_employee_role_permissions(employee, role, *, enabled=True):
    """Create missing action rows for a role; leave existing toggles unchanged."""
    if not employee or not employee.pk or not role:
        return
    codes = activity_codes_for_role(role)
    if not codes:
        return
    existing = set(
        EmployeeActivityPermission.objects.filter(
            employee=employee,
            role=role,
            activity_code__in=codes,
        ).values_list("activity_code", flat=True)
    )
    missing = [
        EmployeeActivityPermission(
            employee=employee,
            role=role,
            activity_code=code,
            is_enabled=enabled,
        )
        for code in codes
        if code not in existing
    ]
    if missing:
        EmployeeActivityPermission.objects.bulk_create(missing, ignore_conflicts=True)


def grant_all_permissions_for_employee(employee):
    """Enable every module action for every assigned role (used on approval)."""
    if not employee or not employee.pk:
        return
    roles = employee.role_values() or ([employee.role] if employee.role else [])
    with transaction.atomic():
        for role in roles:
            codes = activity_codes_for_role(role)
            if not codes:
                continue
            ensure_employee_role_permissions(employee, role, enabled=True)
            EmployeeActivityPermission.objects.filter(
                employee=employee,
                role=role,
                activity_code__in=codes,
            ).update(is_enabled=True)
    invalidate_employee_permission_cache(employee.pk)


def set_employee_activity_permission(employee, role, activity_code, enabled):
    activity_code = (activity_code or "").strip()
    role = (role or "").strip().upper()
    if activity_code not in activity_codes_for_role(role):
        raise ValueError("Unknown activity for this role.")
    permission, _created = EmployeeActivityPermission.objects.update_or_create(
        employee=employee,
        role=role,
        activity_code=activity_code,
        defaults={"is_enabled": bool(enabled)},
    )
    invalidate_employee_permission_cache(getattr(employee, "pk", None), role=role)
    return permission


def _legacy_base_code(activity_code):
    """Map action codes back to older module-only codes when present."""
    parts = (activity_code or "").rsplit(".", 1)
    if len(parts) == 2 and parts[1] in KNOWN_ACTIONS:
        return parts[0]
    return None


def employee_has_activity_permission(employee, activity_code, *, role=None):
    """
    Return whether the employee may perform a module action.

    Missing rows default to allowed so approved staff keep access until rows exist.
    Explicit is_enabled=False restricts access.
    """
    if not employee or not getattr(employee, "pk", None):
        return False
    if not getattr(employee, "is_active", False):
        return False
    if getattr(employee, "approval_status", None) != Employee.ApprovalStatus.APPROVED:
        return False
    if getattr(employee, "is_suspended", False):
        return False

    roles = [role] if role else (employee.role_values() or [])
    roles = [value for value in roles if value]
    if not roles:
        return False

    activity_code = (activity_code or "").strip()
    if not activity_code:
        return False

    cache_role = roles[0] if len(roles) == 1 else ",".join(sorted(roles))
    epoch = _permission_epoch(employee.pk, cache_role)
    cache_key = f"{_permission_cache_key(employee.pk, cache_role, activity_code)}:{epoch}"
    cached = cache.get(cache_key)
    if cached is not None:
        return bool(cached)

    allowed = _resolve_activity_permission(employee, activity_code, roles)
    cache.set(cache_key, allowed, _PERMISSION_CACHE_TTL)
    return allowed


def _resolve_activity_permission(employee, activity_code, roles):
    relevant_roles = [
        value for value in roles if activity_code in activity_codes_for_role(value)
    ]
    # Allow checking via module base + action helper even when role list is filtered.
    if not relevant_roles:
        legacy = _legacy_base_code(activity_code)
        if legacy:
            relevant_roles = [
                value
                for value in roles
                if any(
                    item["code"] == legacy or item["code"].startswith(f"{legacy}.")
                    for item in activities_for_role(value)
                )
            ]
    if not relevant_roles:
        return False

    states = list(
        EmployeeActivityPermission.objects.filter(
            employee=employee,
            role__in=relevant_roles,
            activity_code=activity_code,
        ).values_list("is_enabled", flat=True)
    )
    if states:
        return any(states)

    # Fall back to legacy module-level permission if action rows are not yet created.
    legacy = _legacy_base_code(activity_code)
    if legacy:
        legacy_states = list(
            EmployeeActivityPermission.objects.filter(
                employee=employee,
                role__in=relevant_roles,
                activity_code=legacy,
            ).values_list("is_enabled", flat=True)
        )
        if legacy_states:
            return any(legacy_states)
    return True


def employee_has_module_action(employee, module_code, action, *, role=None):
    return employee_has_activity_permission(
        employee,
        module_action_code(module_code, action),
        role=role,
    )


def permission_state_map(employee, role):
    """Return {activity_code: bool} for one employee/role, defaulting missing to True."""
    codes = activity_codes_for_role(role)
    stored = {
        row.activity_code: row.is_enabled
        for row in EmployeeActivityPermission.objects.filter(
            employee=employee,
            role=role,
            activity_code__in=codes,
        )
    }
    # Inherit from legacy base codes when action rows are absent.
    legacy_rows = {
        row.activity_code: row.is_enabled
        for row in EmployeeActivityPermission.objects.filter(employee=employee, role=role)
        if row.activity_code not in codes
    }
    result = {}
    for code in codes:
        if code in stored:
            result[code] = stored[code]
            continue
        legacy = _legacy_base_code(code)
        if legacy in legacy_rows:
            result[code] = legacy_rows[legacy]
        else:
            result[code] = True
    return result
