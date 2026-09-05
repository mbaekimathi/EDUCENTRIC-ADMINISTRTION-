from django.core.cache import cache

from .models import Employee, SchoolProfile
from .workspace import (
    can_choose_own_workspace_role,
    can_switch_workspace_role,
    exam_management_url_names,
    is_workspace_preview,
    prefetch_user_roles,
    uses_profile_settings,
    user_role_values,
    workspace_role,
    workspace_role_label,
    workspace_view_employee,
)


def school_branding(request):
    """Expose the singleton school profile on public auth pages and workspaces."""
    try:
        profile = SchoolProfile.objects.filter(pk=1).first()
    except Exception:
        profile = None
    return {"school_profile": profile}


def workspace(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    prefetch_user_roles(user)
    role = workspace_role(request)
    view_employee = workspace_view_employee(request)
    can_switch = can_switch_workspace_role(user)
    own_roles = user_role_values(user)
    teacher_is_class_teacher = False
    teacher_has_elearning = False
    if role == Employee.Role.TEACHER and view_employee is not None:
        from apps.curriculum.models import AcademicClass, ELearningSubjectAllocation

        cache_key = f"teacher_nav_flags:{view_employee.pk}"
        flags = cache.get(cache_key)
        if flags is None:
            flags = (
                AcademicClass.objects.filter(
                    class_teacher=view_employee,
                    status=AcademicClass.Status.ACTIVE,
                ).exists(),
                ELearningSubjectAllocation.objects.filter(
                    teacher=view_employee,
                ).exists(),
            )
            cache.set(cache_key, flags, 300)
        teacher_is_class_teacher, teacher_has_elearning = flags
    return {
        "workspace_role": role,
        "workspace_role_label": workspace_role_label(role),
        "uses_profile_settings": uses_profile_settings(role),
        "can_switch_workspace_role": can_switch,
        "can_choose_own_workspace_role": can_choose_own_workspace_role(user),
        "own_workspace_roles": [
            (value, label)
            for value, label in Employee.Role.choices
            if value in own_roles
        ],
        "own_workspace_role_values": own_roles,
        "workspace_role_choices": Employee.Role.choices,
        "workspace_view_employee": view_employee,
        "teacher_is_class_teacher": teacher_is_class_teacher,
        "teacher_has_elearning": teacher_has_elearning,
        "is_role_preview": is_workspace_preview(request),
        "admissions_enabled": _admissions_enabled(),
        **exam_management_url_names(role),
    }


def _admissions_enabled():
    cache_key = "admissions_enabled"
    enabled = cache.get(cache_key)
    if enabled is None:
        try:
            from apps.admissions.models import AdmissionSettings

            enabled = AdmissionSettings.get_solo().admissions_enabled
        except Exception:
            enabled = True
        cache.set(cache_key, enabled, 60)
    return bool(enabled)
