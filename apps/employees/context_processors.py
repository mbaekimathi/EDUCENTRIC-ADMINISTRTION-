from .models import Employee
from .workspace import (
    can_switch_workspace_role,
    workspace_role,
    workspace_role_label,
    workspace_view_employee,
)


def workspace(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    role = workspace_role(request)
    view_employee = workspace_view_employee(request)
    can_switch = can_switch_workspace_role(user)
    teacher_is_class_teacher = False
    teacher_has_elearning = False
    if role == Employee.Role.TEACHER and view_employee is not None:
        from apps.curriculum.models import AcademicClass, ELearningSubjectAllocation

        teacher_is_class_teacher = AcademicClass.objects.filter(
            class_teacher=view_employee,
            status=AcademicClass.Status.ACTIVE,
        ).exists()
        teacher_has_elearning = ELearningSubjectAllocation.objects.filter(
            teacher=view_employee,
        ).exists()
    return {
        "workspace_role": role,
        "workspace_role_label": workspace_role_label(role),
        "can_switch_workspace_role": can_switch,
        "workspace_role_choices": Employee.Role.choices,
        "workspace_view_employee": view_employee,
        "teacher_is_class_teacher": teacher_is_class_teacher,
        "teacher_has_elearning": teacher_has_elearning,
        "is_role_preview": can_switch
        and view_employee is not None
        and (role != user.role or view_employee.pk != user.pk),
    }
