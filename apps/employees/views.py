from collections import OrderedDict, defaultdict
from datetime import date, datetime
from itertools import groupby
import json
import re
from types import SimpleNamespace

from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.messages import error, success
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q, Value
from django.db.models.functions import Concat
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from apps.admissions.forms import AdmissionSettingsForm, StudentWorkspaceForm
from apps.employees.exam_report_export import build_exam_report_excel
from apps.admissions.models import AdmissionSettings, Student
from apps.curriculum.forms import (
    AcademicLevelForm,
    AcademicYearForm,
    ELearningLearningMaterialForm,
    ExamScheduleActivityFormSet,
    ExamScheduleProfileForm,
    GradeBandForm,
    LearningAreaForm,
    LearningScheduleActivityFormSet,
    LearningScheduleProfileForm,
    parse_academic_class_rows,
    parse_academic_term_rows,
    sync_academic_classes,
    sync_academic_terms,
)
from apps.curriculum.models import (
    AcademicClass,
    AcademicLevel,
    AcademicTerm,
    AcademicYear,
    CombinedExamSubject,
    CombinedExamSubjectComponent,
    ClassAttendanceRecord,
    ClassAttendanceSession,
    ClassSubjectAllocation,
    ClassSubjectLessonPlan,
    ClassSubjectOutcome,
    ELearningAttendanceRecord,
    ELearningAttendanceSession,
    ELearningAssessment,
    ELearningAssessmentMark,
    ELearningLearningMaterial,
    ELearningSubjectAllocation,
    ELearningSubjectLessonPlan,
    ELearningSubjectOutcome,
    ExamScheduleActivity,
    ExamScheduleProfile,
    ExamMark,
    ExamSubjectSetting,
    ExamSupervisorAllocation,
    ExamTimetableSession,
    GeneratedExamSitting,
    GeneratedExamTimetable,
    GeneratedELearningLesson,
    GeneratedELearningTimetable,
    GeneratedLearningLesson,
    GeneratedLearningTimetable,
    GradeBand,
    LearningArea,
    LearningScheduleActivity,
    LearningScheduleProfile,
    SubjectAttendanceRecord,
    SubjectAttendanceSession,
)
from apps.curriculum.schedule_preview import (
    DAY_ORDER,
    WEEKDAY_LABELS,
    build_schedule_preview,
    minutes_to_time,
    to_minutes,
)
from apps.curriculum.supervisor_allocator import shuffle_level_supervisors
from apps.curriculum.timetable_generator import (
    build_class_plans,
    build_elearning_level_plans,
    build_exam_class_plans,
    exam_dates_for_subjects,
    exam_slots_from_profile,
    generate_exam_timetable_plan,
    generate_timetable_plan,
    persist_elearning_timetable_plan,
    persist_exam_timetable_plan,
    persist_timetable_plan,
    resolve_elearning_schedule_profile,
    resolve_exam_schedule_profile,
    resolve_schedule_profile,
    lesson_slots_from_profile,
)

from .db_bulk import bulk_upsert_by_keys
from .forms import (
    EmployeeAccountSettingsForm,
    EmployeeLoginForm,
    EmployeePasswordChangeForm,
    EmployeeProfileForm,
    EmployeeRegistrationForm,
    SchoolProfileAcademicSetupForm,
    SchoolProfileBrandingForm,
    SchoolProfileComplianceForm,
    SchoolProfileContactLocationForm,
    SchoolProfileFinancialForm,
    SchoolProfileForm,
    SchoolProfileLeadershipForm,
    SchoolProfileOperationsForm,
)
from .models import Employee, SchoolProfile
from .phone_countries import PHONE_COUNTRIES, parse_stored_phone
from .workspace import (
    ACTIVE_WORKSPACE_ROLE_SESSION_KEY,
    WORKSPACE_ROLE_SESSION_KEY,
    WORKSPACE_VIEW_EMPLOYEE_SESSION_KEY,
    can_switch_workspace_role,
    clear_active_workspace_role,
    clear_workspace_preview,
    employees_for_workspace_role,
    is_workspace_preview,
    needs_login_role_selection,
    set_active_workspace_role,
    user_role_values,
    uses_profile_settings,
    workspace_role,
    workspace_view_employee,
)


def redirect_to_role_dashboard(employee_or_request):
    if hasattr(employee_or_request, "user"):
        role = workspace_role(employee_or_request)
    else:
        roles = (
            employee_or_request.role_values()
            if hasattr(employee_or_request, "role_values")
            else [employee_or_request.role]
        )
        role = employee_or_request.role if employee_or_request.role in roles else (roles[0] if roles else employee_or_request.role)
    return redirect("employees:role_dashboard", role=role.lower())


def _post_login_redirect(request, user, next_url=""):
    roles = user_role_values(user)
    if len(roles) > 1:
        if next_url:
            request.session["post_role_selection_next"] = next_url
        return redirect("employees:select_login_role")
    if roles:
        set_active_workspace_role(request, roles[0])
    if next_url:
        return redirect(next_url)
    return redirect_to_role_dashboard(request if request.user.is_authenticated else user)


def _category_label(value):
    label = (value or "").strip()
    return label.upper() if label else "UNCATEGORIZED"


def group_academic_levels_by_category(levels):
    grouped = []
    ordered = sorted(levels, key=lambda level: (_category_label(level.category), level.order, level.name.lower()))
    for category, items in groupby(ordered, key=lambda level: _category_label(level.category)):
        grouped.append({"category": category, "levels": list(items)})
    return grouped


def group_learning_areas_by_category(areas):
    grouped = OrderedDict()
    for area in areas:
        levels = list(area.academic_levels.all())
        if levels:
            primary = min(levels, key=lambda level: (level.order, level.name.lower()))
            category = _category_label(primary.category)
        else:
            category = "UNASSIGNED"
        grouped.setdefault(category, []).append(area)
    return [
        {
            "category": category,
            "areas": sorted(items, key=lambda area: (area.display_order, area.name.lower())),
        }
        for category, items in grouped.items()
    ]


@never_cache
@require_http_methods(["GET", "POST"])
def employee_login(request):
    if request.user.is_authenticated:
        if needs_login_role_selection(request):
            return redirect("employees:select_login_role")
        return redirect_to_role_dashboard(request)

    form = EmployeeLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        next_url = (request.POST.get("next") or "").strip()
        return _post_login_redirect(request, user, next_url)
    return render(request, "employees/login.html", {"form": form})


@never_cache
def employee_logout(request):
    clear_workspace_preview(request)
    clear_active_workspace_role(request)
    request.session.pop("post_role_selection_next", None)
    logout(request)
    return redirect("employees:login")


@login_required
@require_http_methods(["GET", "POST"])
def select_login_role(request):
    roles = user_role_values(request.user)
    if len(roles) <= 1:
        if roles:
            set_active_workspace_role(request, roles[0])
        next_url = request.session.pop("post_role_selection_next", None)
        if next_url:
            return redirect(next_url)
        return redirect_to_role_dashboard(request)

    role_choices = [
        (value, label)
        for value, label in Employee.Role.choices
        if value in roles
    ]
    error_message = ""
    if request.method == "POST":
        selected = (request.POST.get("role") or "").upper()
        if set_active_workspace_role(request, selected):
            # Acting as yourself clears any IT Support impersonation preview.
            if selected == request.user.role or selected in roles:
                clear_workspace_preview(request)
            next_url = request.session.pop("post_role_selection_next", None)
            if next_url:
                return redirect(next_url)
            return redirect("employees:role_dashboard", role=selected.lower())
        error_message = "Select one of your assigned roles to continue."

    return render(
        request,
        "employees/select_login_role.html",
        {
            "role_choices": role_choices,
            "error_message": error_message,
            "employee_name": request.user.display_name,
        },
    )


@require_http_methods(["GET", "POST"])
def employee_register(request):
    form = EmployeeRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        success(
            request,
            "Registration submitted. Your account is pending administrator approval.",
        )
        return redirect("employees:login")
    return render(
        request,
        "employees/register.html",
        {
            "form": form,
            "phone_countries_json": list(PHONE_COUNTRIES),
        },
    )


@login_required
def dashboard(request):
    return redirect_to_role_dashboard(request)


IT_SUPPORT_MODULES = (
    {
        "slug": "human-resource-management",
        "title": "Human resource management",
        "icon": "HR",
        "summary": "Staff records, roles, and people operations.",
        "copy": "Use this workspace to manage employees, assignments, and HR workflows.",
    },
    {
        "slug": "student-management",
        "title": "Student management",
        "icon": "ST",
        "summary": "Admissions, enrolment, and student records.",
        "copy": "Use this workspace to manage student records, admissions, and enrolment.",
    },
    {
        "slug": "curriculum-management",
        "title": "Curriculum management",
        "icon": "CU",
        "summary": "Academic structure, subjects, and assessment setup.",
        "copy": "Use this workspace to manage academic levels, learning areas, and assessment.",
    },
    {
        "slug": "financial-management",
        "title": "Financial management",
        "icon": "FN",
        "summary": "Fees, billing, and school finances.",
        "copy": "Use this workspace to manage fees, billing, and financial operations.",
    },
    {
        "slug": "stock-management",
        "title": "Stock management",
        "icon": "SK",
        "summary": "Inventory, stores, and supply tracking.",
        "copy": "Use this workspace to manage school inventory and store operations.",
    },
    {
        "slug": "reports",
        "title": "Reports",
        "icon": "RP",
        "summary": "Operational summaries and school insights.",
        "copy": "Use this workspace to open operational summaries and school reports.",
    },
)

IT_SUPPORT_REPORT_SECTIONS = (
    {
        "slug": "curriculum-reports",
        "title": "Curriculum reports",
        "icon": "CR",
        "summary": "Academic performance, attendance, and curriculum insights.",
        "copy": "Open curriculum reports covering learning, assessments, and academic progress.",
    },
    {
        "slug": "financial-reports",
        "title": "Financial reports",
        "icon": "FR",
        "summary": "Fees, billing, and financial summaries.",
        "copy": "Open financial reports covering fees, payments, and school finance.",
    },
    {
        "slug": "store-reports",
        "title": "Store reports",
        "icon": "SR",
        "summary": "Inventory, stock, and store operations.",
        "copy": "Open store reports covering inventory levels and supply activity.",
    },
)

IT_SUPPORT_CURRICULUM_REPORT_PAGES = (
    {
        "slug": "learning-reports",
        "title": "Learning reports",
        "icon": "LR",
        "summary": "Attendance, timetable, and learning progress reports.",
        "copy": "Review learning reports for classes, attendance, and timetable delivery.",
    },
    {
        "slug": "exam-reports",
        "title": "Assessment reports",
        "icon": "ER",
        "summary": "Assessment performance, coverage, and outcome reports.",
        "copy": "Review assessment reports for results, coverage, and outcomes.",
    },
)

SECRETARY_REPORT_SECTIONS = (
    {
        "slug": "curriculum-reports",
        "title": "Curriculum reports",
        "icon": "CR",
        "summary": "Academic performance, attendance, and curriculum insights.",
        "copy": "Open curriculum reports covering learning, assessments, and academic progress.",
    },
    {
        "slug": "financial-reports",
        "title": "Financial reports",
        "icon": "FR",
        "summary": "Fees, billing, and financial summaries.",
        "copy": "Open financial reports covering fees, payments, and school finance.",
    },
    {
        "slug": "store-reports",
        "title": "Store reports",
        "icon": "SR",
        "summary": "Inventory, stock, and store operations.",
        "copy": "Open store reports covering inventory levels and supply activity.",
    },
)

IT_SUPPORT_CURRICULUM_SECTIONS = (
    {
        "slug": "learning-management",
        "title": "Learning management",
        "icon": "LM",
        "summary": "Academic levels, learning areas, and learning timetables.",
        "copy": "Manage academic structure, subjects, and regular learning timetables.",
    },
    {
        "slug": "e-learning-management",
        "title": "E-learning management",
        "icon": "EL",
        "summary": "Online courses, digital content, and remote learning tools.",
        "copy": "Manage e-learning courses, digital content, and online learning delivery.",
    },
    {
        "slug": "exam-management",
        "title": "Assessment management",
        "icon": "EM",
        "summary": "Assessment settings, timetables, supervisors, and grading.",
        "copy": "Manage assessment configuration, supervisors, timetables, and academic grading.",
    },
)

IT_SUPPORT_ELEARNING_PAGES = (
    {
        "slug": "allocate-subjects",
        "title": "Allocate subjects",
        "icon": "AS",
        "summary": "Assign teachers to subjects for e-learning delivery.",
        "copy": "Choose which teacher owns each subject for e-learning at every academic level.",
    },
    {
        "slug": "timetable-generation",
        "title": "Generate e-learning timetable",
        "icon": "TG",
        "summary": "Build e-learning timetables from subject allocations.",
        "copy": "Generate e-learning timetables from teacher allocations for each academic level.",
    },
    {
        "slug": "attendance",
        "title": "E-learning attendance",
        "icon": "EA",
        "summary": "Track attendance for e-learning sessions.",
        "copy": "Record and review attendance for e-learning classes and sessions.",
    },
    {
        "slug": "assessments",
        "title": "E-learning assessments",
        "icon": "ES",
        "summary": "Manage quizzes, tests, and online assessments.",
        "copy": "Create and review assessments delivered through e-learning.",
    },
    {
        "slug": "learning-materials",
        "title": "Public learning materials",
        "icon": "PM",
        "summary": "Publish and manage public e-learning materials.",
        "copy": "Share learning materials that learners can access publicly through e-learning.",
    },
)

IT_SUPPORT_EXAM_PAGES = (
    {
        "slug": "allocate-supervisors",
        "title": "Allocate supervisors",
        "icon": "AS",
        "summary": "Auto-allocate assessment supervisors for each academic level.",
        "copy": "Shuffle supervisors across subjects for the academic level. Classes in the level sit as one group.",
    },
    {
        "slug": "exam-timetable-generation",
        "title": "Generate assessment timetable",
        "icon": "EG",
        "summary": "Build assessment timetables from the assessment profile.",
        "copy": "Generate assessment timetables from the assessment timetable profile for each academic level. Supervisors can be assigned before or after generation.",
    },
    {
        "slug": "exam-records",
        "title": "All assessments",
        "icon": "AE",
        "summary": "Review every registered assessment by academic year and term.",
        "copy": "Every generated assessment timetable is listed here so you can open and manage registered assessments.",
    },
)

IT_SUPPORT_LEARNING_PAGES = (
    {
        "slug": "class-management",
        "title": "Class management",
        "icon": "CM",
        "summary": "Allocate class teachers to academic classes.",
        "copy": "Assign an approved teacher as class teacher for each academic class.",
    },
    {
        "slug": "timetable-management",
        "title": "Timetable management",
        "icon": "TM",
        "summary": "Learning timetable structure and sessions.",
        "copy": "Manage the timetable structure used for regular learning sessions.",
    },
)

IT_SUPPORT_CLASS_PAGES = (
    {
        "slug": "student-attendance-progress",
        "title": "Student attendance & progress",
        "icon": "SA",
        "summary": "Track student attendance and academic progress.",
        "copy": "Record and review student attendance and class progress.",
    },
    {
        "slug": "teacher-attendance-progress",
        "title": "Teacher attendance & progress",
        "icon": "TA",
        "summary": "Track teacher attendance and teaching progress.",
        "copy": "Record and review teacher attendance and class delivery progress.",
    },
)

TEACHER_MY_CLASS_PAGES = (
    {
        "slug": "register-class-attendance",
        "title": "Register class attendance",
        "icon": "RA",
        "summary": "Mark morning, afternoon, and evening attendance.",
        "copy": "Record daily class attendance for students in your class.",
    },
    {
        "slug": "students-class-attendance",
        "title": "Students class attendance",
        "icon": "CA",
        "summary": "Review class attendance analytics by day, period, term, or year.",
        "copy": "Analyse morning, afternoon, and evening attendance for your class.",
    },
    {
        "slug": "students-discipline",
        "title": "Students discipline",
        "icon": "SD",
        "summary": "Track behaviour and discipline notes.",
        "copy": "Record and review discipline cases for students in your class.",
    },
    {
        "slug": "student-books",
        "title": "Student books",
        "icon": "SB",
        "summary": "Manage issued and returned student books.",
        "copy": "Track books issued to students in your class.",
    },
)

TEACHER_ELEARNING_PAGES = (
    {
        "slug": "attendance",
        "title": "E-learning attendance",
        "icon": "EA",
        "summary": "Track attendance for e-learning sessions.",
        "copy": "Record and review attendance for your e-learning sessions.",
    },
    {
        "slug": "assessments",
        "title": "E-learning assessments",
        "icon": "ES",
        "summary": "Manage quizzes, tests, and online assessments.",
        "copy": "Create and review assessments for your e-learning subjects.",
    },
    {
        "slug": "learning-materials",
        "title": "Learning materials",
        "icon": "LM",
        "summary": "Share materials for your e-learning subjects.",
        "copy": "Publish and manage learning materials for your allocated e-learning subjects.",
    },
)

TEACHER_ELEARNING_REPORT_PAGES = (
    {
        "slug": "e-learning-reports",
        "title": "E-learning reports",
        "icon": "ER",
        "summary": "Combined readiness report for your e-learning subjects.",
        "copy": "Attendance, lesson plans, outcomes, and materials for subjects allocated to you in this session.",
    },
)

IT_SUPPORT_TIMETABLE_PAGES = (
    {
        "slug": "class-and-subject-allocation",
        "title": "Class and subject allocation",
        "icon": "CA",
        "summary": "Assign classes, subjects, and teachers.",
        "copy": "Allocate classes and subjects to teachers for timetable planning.",
    },
    {
        "slug": "timetable-generation",
        "title": "Timetable generation",
        "icon": "TG",
        "summary": "Build and publish learning timetables.",
        "copy": "Generate learning timetables from class and subject allocations.",
    },
    {
        "slug": "timetable-analytics",
        "title": "Timetable analytics",
        "icon": "TA",
        "summary": "Review timetable coverage and clashes.",
        "copy": "Analyse timetable coverage, teacher load, and scheduling conflicts.",
    },
)


def _it_support_module(slug):
    for module in IT_SUPPORT_MODULES:
        if module["slug"] == slug:
            return module
    return None


def _it_support_report_section(slug):
    for section in IT_SUPPORT_REPORT_SECTIONS:
        if section["slug"] == slug:
            return section
    return None


def _it_support_curriculum_report_page(slug):
    for page in IT_SUPPORT_CURRICULUM_REPORT_PAGES:
        if page["slug"] == slug:
            return page
    return None


def _require_it_support(request):
    if workspace_role(request) != Employee.Role.IT_SUPPORT:
        return redirect_to_role_dashboard(request)
    return None


def _it_support_performance_context():
    from apps.employees.system_performance import get_system_performance_snapshot

    return {
        "metrics_url": reverse("employees:it_support_system_performance_metrics"),
        "performance_snapshot": get_system_performance_snapshot(),
    }


@login_required
@require_http_methods(["GET"])
def it_support_system_performance(request):
    denied = _require_it_support(request)
    if denied:
        return denied
    context = {"active_nav": "system_performance"}
    context.update(_it_support_performance_context())
    return render(request, "employees/it_support_system_performance.html", context)


@login_required
@require_http_methods(["GET"])
def it_support_system_performance_metrics(request):
    denied = _require_it_support(request)
    if denied:
        return JsonResponse({"error": "forbidden"}, status=403)
    from apps.employees.system_performance import get_system_performance_snapshot

    return JsonResponse(get_system_performance_snapshot())


def _secretary_report_section(slug):
    for section in SECRETARY_REPORT_SECTIONS:
        if section["slug"] == slug:
            return section
    return None


def _require_secretary(request):
    if workspace_role(request) != Employee.Role.SECRETARY:
        return redirect_to_role_dashboard(request)
    return None


def _require_curriculum_reports(request):
    role = workspace_role(request)
    if role not in (Employee.Role.IT_SUPPORT, Employee.Role.SECRETARY):
        return redirect_to_role_dashboard(request), None
    return None, role


def _curriculum_report_urls(role):
    if role == Employee.Role.SECRETARY:
        return {
            "curriculum_report_page_url": "employees:secretary_curriculum_report_page",
            "exam_report_students_url": "employees:secretary_exam_report_students",
            "exam_report_export_url": "employees:secretary_exam_report_export",
        }
    return {
        "curriculum_report_page_url": "employees:it_support_curriculum_report_page",
        "exam_report_students_url": "employees:it_support_exam_report_students",
        "exam_report_export_url": "employees:it_support_exam_report_export",
    }


def _curriculum_reports_redirect(role):
    if role == Employee.Role.SECRETARY:
        return redirect("employees:secretary_report_section", section="curriculum-reports")
    return redirect("employees:it_support_report_section", section="curriculum-reports")


def _require_teacher_workspace(request):
    if workspace_role(request) != Employee.Role.TEACHER:
        return redirect_to_role_dashboard(request)
    if request.method == "POST" and is_workspace_preview(request):
        error(
            request,
            "You are viewing another employee's session. Open this role as yourself for full access.",
        )
        return redirect_to_role_dashboard(request)
    return None


def _teacher_allocated_levels(employee):
    allocations = (
        ClassSubjectAllocation.objects.filter(teacher=employee)
        .select_related("academic_class", "academic_class__academic_level")
        .order_by(
            "academic_class__academic_level__order",
            "academic_class__academic_level__name",
            "academic_class__order",
            "academic_class__name",
        )
    )
    grouped = OrderedDict()
    for allocation in allocations:
        academic_class = allocation.academic_class
        level = academic_class.academic_level
        if level.status != AcademicLevel.Status.ACTIVE:
            continue
        if academic_class.status != AcademicClass.Status.ACTIVE:
            continue
        group = grouped.setdefault(level.id, {"level": level, "classes": OrderedDict()})
        group["classes"][academic_class.id] = academic_class
    return [
        {"level": item["level"], "classes": list(item["classes"].values())}
        for item in grouped.values()
    ]


def _class_group_values(academic_class):
    name = (academic_class.name or "").strip()
    code = (academic_class.code or "").strip()
    level = academic_class.academic_level
    level_code = (level.code or "").strip()
    level_name = (level.name or "").strip()
    values = {name, code, level_name}
    compact = lambda value: re.sub(r"[^A-Za-z0-9]", "", value or "")
    values.update({compact(name), compact(code), compact(level_code)})
    stripped_code = re.match(r"^[A-Za-z]*(\d+.*)$", code)
    if stripped_code:
        values.add(stripped_code.group(1))
    level_digits = re.search(r"(\d+)", level_code) or re.search(r"(\d+)", level_name)
    stream = compact(name)
    if level_digits and stream and not re.search(level_digits.group(1), stream):
        values.add(f"{level_digits.group(1)}{stream}")
        values.add(f"{level_digits.group(1)} {name}")
    return {value for value in values if value}


def _teacher_class_subjects(employee, academic_class, level):
    allocated_ids = list(
        ClassSubjectAllocation.objects.filter(teacher=employee, academic_class=academic_class)
        .order_by("learning_area__display_order", "learning_area__name")
        .values_list("learning_area_id", flat=True)
    )
    if not allocated_ids:
        return []
    exam_subjects = _exam_record_subjects(level, academic_class)
    exam_by_id = {subject.id: subject for subject in exam_subjects}
    subjects = [exam_by_id[subject_id] for subject_id in allocated_ids if subject_id in exam_by_id]
    missing_ids = [subject_id for subject_id in allocated_ids if subject_id not in exam_by_id]
    if missing_ids:
        extras = list(
            LearningArea.objects.filter(id__in=missing_ids).order_by("display_order", "name")
        )
        extra_order = {subject_id: index for index, subject_id in enumerate(allocated_ids)}
        extras.sort(key=lambda subject: extra_order.get(subject.id, 99))
        subjects.extend(extras)
    return subjects


def _teacher_exam_subject_groups(employee, generation):
    exam_level_ids = set(generation.academic_levels.values_list("id", flat=True))
    allocations = (
        ClassSubjectAllocation.objects.filter(teacher=employee)
        .select_related(
            "learning_area",
            "academic_class",
            "academic_class__academic_level",
        )
        .order_by(
            "academic_class__academic_level__order",
            "academic_class__academic_level__name",
            "learning_area__display_order",
            "learning_area__name",
            "academic_class__order",
            "academic_class__name",
        )
    )
    grouped = OrderedDict()
    for allocation in allocations:
        academic_class = allocation.academic_class
        level = academic_class.academic_level
        if level.status != AcademicLevel.Status.ACTIVE:
            continue
        if academic_class.status != AcademicClass.Status.ACTIVE:
            continue
        if exam_level_ids and level.id not in exam_level_ids:
            continue
        group = grouped.setdefault(level.id, {"level": level, "subjects": []})
        group["subjects"].append(
            {
                "subject": allocation.learning_area,
                "academic_class": academic_class,
            }
        )
    return list(grouped.values())


def _teacher_exam_class_groups(employee, generation):
    exam_level_ids = set(generation.academic_levels.values_list("id", flat=True))
    groups = []
    for group in _teacher_allocated_levels(employee):
        if exam_level_ids and group["level"].id not in exam_level_ids:
            continue
        if group["classes"]:
            groups.append({"level": group["level"], "classes": group["classes"]})
    return groups


def _teacher_exam_classes(employee, generation):
    classes = []
    for group in _teacher_exam_class_groups(employee, generation):
        classes.extend(group["classes"])
    return classes


def _teacher_session_timetable(employee):
    """Build a personal weekday × period grid from this teacher's generated lessons."""
    lessons = list(
        GeneratedLearningLesson.objects.filter(teacher=employee)
        .select_related(
            "academic_class",
            "academic_class__academic_level",
            "academic_level",
            "learning_area",
            "teacher",
        )
        .order_by("weekday", "start_time", "academic_class__order", "academic_class__name")
    )
    if not lessons:
        return None

    days = [day for day in DAY_ORDER if any(item.weekday == day for item in lessons)]
    periods = []
    seen_periods = set()
    for lesson in sorted(lessons, key=lambda item: (item.start_time, item.end_time, item.period_name)):
        start = to_minutes(lesson.start_time)
        end = to_minutes(lesson.end_time)
        period_key = (start, end, lesson.period_name)
        if period_key in seen_periods:
            continue
        seen_periods.add(period_key)
        periods.append(
            {
                "name": lesson.period_name,
                "start": start,
                "end": end,
                "start_label": lesson.start_time.strftime("%H:%M"),
                "end_label": lesson.end_time.strftime("%H:%M"),
            }
        )

    lookup = {}
    for lesson in lessons:
        key = (lesson.weekday, to_minutes(lesson.start_time))
        lookup.setdefault(key, []).append(lesson)

    rows = []
    for day in days:
        cells = []
        for period in periods:
            cell_lessons = lookup.get((day, period["start"]), [])
            cells.append(
                {
                    "lessons": cell_lessons,
                    "lesson": cell_lessons[0] if cell_lessons else None,
                    "is_blank": not cell_lessons,
                }
            )
        rows.append(
            {
                "day_code": day,
                "day_label": WEEKDAY_LABELS.get(day, day),
                "cells": cells,
            }
        )
    return {
        "lesson_count": len(lessons),
        "periods": periods,
        "rows": rows,
    }


def _teacher_elearning_timetable(employee):
    """Build a personal weekday × period grid from this teacher's e-learning lessons."""
    lessons = list(
        GeneratedELearningLesson.objects.filter(teacher=employee)
        .select_related("academic_level", "learning_area", "teacher")
        .order_by("weekday", "start_time", "academic_level__order", "academic_level__name")
    )
    if not lessons:
        return None

    days = [day for day in DAY_ORDER if any(item.weekday == day for item in lessons)]
    periods = []
    seen_periods = set()
    for lesson in sorted(lessons, key=lambda item: (item.start_time, item.end_time, item.period_name)):
        start = to_minutes(lesson.start_time)
        end = to_minutes(lesson.end_time)
        period_key = (start, end, lesson.period_name)
        if period_key in seen_periods:
            continue
        seen_periods.add(period_key)
        periods.append(
            {
                "name": lesson.period_name,
                "start": start,
                "end": end,
                "start_label": lesson.start_time.strftime("%H:%M"),
                "end_label": lesson.end_time.strftime("%H:%M"),
            }
        )

    lookup = {}
    for lesson in lessons:
        key = (lesson.weekday, to_minutes(lesson.start_time))
        lookup.setdefault(key, []).append(lesson)

    rows = []
    for day in days:
        cells = []
        for period in periods:
            cell_lessons = lookup.get((day, period["start"]), [])
            cells.append(
                {
                    "lessons": cell_lessons,
                    "lesson": cell_lessons[0] if cell_lessons else None,
                    "is_blank": not cell_lessons,
                }
            )
        rows.append(
            {
                "day_code": day,
                "day_label": WEEKDAY_LABELS.get(day, day),
                "cells": cells,
            }
        )
    return {
        "lesson_count": len(lessons),
        "periods": periods,
        "rows": rows,
    }


def group_employees_by_role(employees):
    grouped = OrderedDict(
        (
            value,
            {"role": value, "label": label, "employees": []},
        )
        for value, label in Employee.Role.choices
    )
    for employee in employees:
        roles = employee.role_values()
        for role in roles:
            group = grouped.get(role)
            if group is None:
                group = {
                    "role": role,
                    "label": dict(Employee.Role.choices).get(role, role),
                    "employees": [],
                }
                grouped[role] = group
            group["employees"].append(employee)
    return [group for group in grouped.values() if group["employees"]]


CLASS_STREAM_RE = re.compile(r"^(\d+)\s*([A-Za-z]+)$")

STUDENT_SORT_NAME = "name"
STUDENT_SORT_ADMISSION = "admission"
STUDENT_SORT_CHOICES = {STUDENT_SORT_NAME, STUDENT_SORT_ADMISSION}


def _resolve_student_sort(request):
    raw = (request.GET.get("sort") or request.POST.get("sort") or "").strip().lower()
    if raw in {"admission", "adm", "admission_number", "admission-no", "admission_no"}:
        return STUDENT_SORT_ADMISSION
    return STUDENT_SORT_NAME


def _student_sort_order_by(sort_mode, *, include_class_group=False):
    if sort_mode == STUDENT_SORT_ADMISSION:
        fields = ("admission_number", "first_name", "last_name")
    else:
        fields = ("first_name", "last_name", "admission_number")
    if include_class_group:
        return ("class_group", *fields)
    return fields


def _student_admission_sort_key(student):
    admission = (student.admission_number or "").strip()
    match = re.match(r"^(\D*?)(\d+)(.*)$", admission, flags=re.IGNORECASE)
    if match:
        prefix, digits, suffix = match.groups()
        return (0, prefix.casefold(), int(digits), suffix.casefold())
    if admission:
        return (1, admission.casefold(), 0, "")
    return (2, "", 0, "")


def _student_name_sort_key(student):
    return (
        (student.first_name or "").casefold(),
        (getattr(student, "middle_name", None) or "").casefold(),
        (student.last_name or "").casefold(),
        _student_admission_sort_key(student),
    )


def _sorted_students(students, sort_mode):
    mode = sort_mode if sort_mode in STUDENT_SORT_CHOICES else STUDENT_SORT_NAME
    if mode == STUDENT_SORT_ADMISSION:
        return sorted(
            students,
            key=lambda student: (_student_admission_sort_key(student), _student_name_sort_key(student)),
        )
    return sorted(students, key=_student_name_sort_key)


def _student_sort_template_context(request, *, anchor=""):
    sort_mode = _resolve_student_sort(request)
    params = request.GET.copy()
    path = request.path

    def build(mode):
        query = params.copy()
        if mode == STUDENT_SORT_ADMISSION:
            query["sort"] = STUDENT_SORT_ADMISSION
        else:
            query.pop("sort", None)
        encoded = query.urlencode()
        href = f"{path}?{encoded}" if encoded else path
        if anchor:
            href = f"{href}#{anchor}"
        return href

    return {
        "student_sort": sort_mode,
        "student_sort_is_admission": sort_mode == STUDENT_SORT_ADMISSION,
        "student_sort_name_url": build(STUDENT_SORT_NAME),
        "student_sort_admission_url": build(STUDENT_SORT_ADMISSION),
    }


def _with_student_sort(url, sort_mode):
    if sort_mode != STUDENT_SORT_ADMISSION:
        return url
    path, hash_part = url, ""
    if "#" in url:
        path, hash_part = url.split("#", 1)
        hash_part = f"#{hash_part}"
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}sort={STUDENT_SORT_ADMISSION}{hash_part}"


def _pending_admission_queryset():
    return Student.objects.filter(is_active=False, is_suspended=False).select_related(
        "parent_guardian"
    )


def _pending_admission_count():
    return _pending_admission_queryset().count()


def _student_management_nav_context(*, active_tool="register"):
    return {
        "active_module": "student-management",
        "active_student_tool": active_tool,
        "pending_admission_count": _pending_admission_count(),
    }


def _student_management_stats():
    from django.db.models import Count

    level_counts = {
        row["academic_level"]: row["count"]
        for row in Student.objects.values("academic_level").annotate(count=Count("id"))
    }
    return {
        "student_count": sum(level_counts.values()),
        "level_count": len(level_counts),
        "class_count": Student.objects.values("academic_level", "class_group").distinct().count(),
        "level_counts": level_counts,
        "pending_admission_count": _pending_admission_count(),
    }


def _student_management_context(request):
    level_labels = dict(Student.AcademicLevel.choices)
    valid_levels = {value for value, _label in Student.AcademicLevel.choices}
    stats = _student_management_stats()
    level_counts = stats["level_counts"]
    sort_mode = _resolve_student_sort(request)

    selected_level = (request.GET.get("level") or "").strip().upper()
    if selected_level not in valid_levels or not level_counts.get(selected_level):
        selected_level = next(
            (value for value, _label in Student.AcademicLevel.choices if level_counts.get(value)),
            "",
        )

    students_qs = Student.objects.select_related("parent_guardian").order_by(
        "academic_level",
        *_student_sort_order_by(sort_mode, include_class_group=True),
    )
    if selected_level:
        students_qs = students_qs.filter(academic_level=selected_level)
    students = list(students_qs)
    student_groups = group_students_by_class(students, sort=sort_mode)
    level_filters = [
        {
            "value": value,
            "label": label,
            "count": level_counts.get(value, 0),
            "is_active": value == selected_level,
        }
        for value, label in Student.AcademicLevel.choices
        if level_counts.get(value)
    ]
    search_query = (request.GET.get("q") or "").strip()
    return {
        "student_groups": student_groups,
        "student_count": stats["student_count"],
        "class_count": stats["class_count"],
        "level_count": stats["level_count"],
        "pending_admission_count": stats["pending_admission_count"],
        "selected_student_level": selected_level,
        "selected_student_level_label": level_labels.get(selected_level, ""),
        "student_level_filters": level_filters,
        "level_student_count": len(students),
        "search_query": search_query,
        "gender_choices": Student.Gender.choices,
        "academic_level_choices": Student.AcademicLevel.choices,
        "sponsorship_choices": Student.SponsorshipCategory.choices,
        **_student_management_nav_context(active_tool="register"),
        **_student_sort_template_context(request),
    }


def _cached_exam_report_builder_catalog():
    from django.core.cache import cache

    cache_key = "exam_report_builder_catalog"
    catalog = cache.get(cache_key)
    if catalog is None:
        catalog = _exam_report_builder_catalog()
        cache.set(cache_key, catalog, 300)
    return catalog


def group_students_by_class(students, sort=STUDENT_SORT_NAME):
    level_rank = {
        value: index
        for index, (value, _label) in enumerate(Student.AcademicLevel.choices)
    }
    level_labels = dict(Student.AcademicLevel.choices)
    levels = OrderedDict()
    sort_mode = sort if sort in STUDENT_SORT_CHOICES else STUDENT_SORT_NAME

    def student_sort_key(student):
        if sort_mode == STUDENT_SORT_ADMISSION:
            return (_student_admission_sort_key(student), _student_name_sort_key(student))
        return _student_name_sort_key(student)

    for student in students:
        raw_class = (student.class_group or "").strip()
        stream_match = CLASS_STREAM_RE.match(raw_class.replace(" ", ""))
        stream_key = stream_match.group(2).upper() if stream_match else ""
        stream_label = f"{stream_match.group(1)}{stream_key}" if stream_match else level_labels.get(
            student.academic_level,
            student.get_academic_level_display(),
        )
        level = student.academic_level
        if level not in levels:
            levels[level] = {
                "level": level,
                "label": level_labels.get(level, student.get_academic_level_display()),
                "streams": OrderedDict(),
            }
        streams = levels[level]["streams"]
        if stream_key not in streams:
            streams[stream_key] = {
                "key": stream_key,
                "label": stream_label,
                "students": [],
            }
        streams[stream_key]["students"].append(student)

    grouped = []
    for level, data in sorted(levels.items(), key=lambda item: level_rank.get(item[0], 99)):
        streams = sorted(data["streams"].values(), key=lambda stream: stream["key"])
        for stream in streams:
            stream["students"].sort(key=student_sort_key)
        grouped.append(
            {
                "level": data["level"],
                "label": data["label"],
                "student_count": sum(len(stream["students"]) for stream in streams),
                "streams": streams,
            }
        )
    return grouped


def _it_support_curriculum_section(slug):
    for section in IT_SUPPORT_CURRICULUM_SECTIONS:
        if section["slug"] == slug:
            return section
    return None


def _it_support_elearning_page(slug):
    for page in IT_SUPPORT_ELEARNING_PAGES:
        if page["slug"] == slug:
            return page
    return None


def _it_support_learning_page(slug):
    for page in IT_SUPPORT_LEARNING_PAGES:
        if page["slug"] == slug:
            return page
    return None


def _it_support_class_page(slug):
    for page in IT_SUPPORT_CLASS_PAGES:
        if page["slug"] == slug:
            return page
    return None


def _teacher_my_class_page(slug):
    for page in TEACHER_MY_CLASS_PAGES:
        if page["slug"] == slug:
            return page
    return None


def _teacher_elearning_page(slug):
    for page in TEACHER_ELEARNING_PAGES:
        if page["slug"] == slug:
            return page
    for page in TEACHER_ELEARNING_REPORT_PAGES:
        if page["slug"] == slug:
            return page
    return None


def _teacher_elearning_report_context(employee, page):
    return {
        "active_nav": "e-learning",
        "active_elearning_tool": page["slug"],
        "page": page,
        "teacher_employee": employee,
        "elearning_pages": TEACHER_ELEARNING_PAGES,
        "elearning_report_pages": TEACHER_ELEARNING_REPORT_PAGES,
    }


def _teacher_elearning_session_allocations(employee):
    return list(
        ELearningSubjectAllocation.objects.filter(teacher=employee)
        .select_related("academic_level", "learning_area")
        .order_by(
            "academic_level__order",
            "academic_level__name",
            "learning_area__display_order",
            "learning_area__name",
        )
    )


def _it_support_timetable_page(slug):
    for page in IT_SUPPORT_TIMETABLE_PAGES:
        if page["slug"] == slug:
            return page
    return None


def _it_support_exam_page(slug):
    for page in IT_SUPPORT_EXAM_PAGES:
        if page["slug"] == slug:
            return page
    return None


def _teacher_led_classes(employee):
    return list(
        AcademicClass.objects.filter(
            class_teacher=employee,
            status=AcademicClass.Status.ACTIVE,
            academic_level__status=AcademicLevel.Status.ACTIVE,
        )
        .select_related("academic_level")
        .order_by("academic_level__order", "academic_level__name", "order", "name")
    )


@login_required
def role_dashboard(request, role):
    current = workspace_role(request)
    if current.lower() != role:
        return redirect_to_role_dashboard(request)
    if current == Employee.Role.IT_SUPPORT:
        context = {
            "active_nav": "dashboard",
            "it_support_modules": IT_SUPPORT_MODULES,
        }
        context.update(_it_support_performance_context())
        return render(request, "employees/it_support_dashboard.html", context)
    if current == Employee.Role.TEACHER:
        employee = workspace_view_employee(request)
        session_timetable = _teacher_session_timetable(employee)
        elearning_timetable = _teacher_elearning_timetable(employee)
        return render(
            request,
            "employees/teacher_dashboard.html",
            {
                "active_nav": "dashboard",
                "session_timetable": session_timetable,
                "elearning_timetable": elearning_timetable,
            },
        )
    if current == Employee.Role.SECRETARY:
        return render(
            request,
            "employees/secretary_dashboard.html",
            {"active_nav": "dashboard"},
        )
    return render(
        request,
        "employees/role_dashboard.html",
        {"active_nav": "dashboard"},
    )


@login_required
def secretary_reports(request):
    denied = _require_secretary(request)
    if denied:
        return denied
    return render(
        request,
        "employees/secretary_reports.html",
        {
            "active_nav": "dashboard",
            "active_module": "reports",
            "report_sections": SECRETARY_REPORT_SECTIONS,
        },
    )


@login_required
def secretary_report_section(request, section):
    denied = _require_secretary(request)
    if denied:
        return denied
    current = _secretary_report_section(section)
    if current is None:
        return redirect("employees:secretary_reports")
    if current["slug"] == "curriculum-reports":
        template = "employees/it_support_curriculum_reports.html"
        extra_context = {
            "curriculum_report_pages": IT_SUPPORT_CURRICULUM_REPORT_PAGES,
            **_curriculum_report_urls(Employee.Role.SECRETARY),
        }
    else:
        template = "employees/secretary_report_section.html"
        extra_context = {}
    return render(
        request,
        template,
        {
            "active_nav": "dashboard",
            "active_module": "reports",
            "active_report": current["slug"],
            "section": current,
            "report_sections": SECRETARY_REPORT_SECTIONS,
            **extra_context,
        },
    )


@login_required
def secretary_curriculum_report_page(request, page):
    denied, role = _require_curriculum_reports(request)
    if denied:
        return denied
    if role != Employee.Role.SECRETARY:
        return redirect_to_role_dashboard(request)
    return _render_curriculum_report_page(request, page, role)


@login_required
def secretary_exam_report_export(request):
    denied, role = _require_curriculum_reports(request)
    if denied:
        return denied
    if role != Employee.Role.SECRETARY:
        return redirect_to_role_dashboard(request)
    return _exam_report_export_response(request, role)


@login_required
def secretary_exam_report_students(request):
    denied, role = _require_curriculum_reports(request)
    if denied:
        return denied
    if role != Employee.Role.SECRETARY:
        return JsonResponse({"students": []}, status=403)
    return _exam_report_students_response(request)


@login_required
@require_http_methods(["GET"])
def teacher_elearning(request):
    denied = _require_teacher_workspace(request)
    if denied:
        return denied
    employee = workspace_view_employee(request)
    has_allocation = ELearningSubjectAllocation.objects.filter(teacher=employee).exists()
    if not has_allocation:
        error(request, "E-learning unlocks when you are allocated an e-learning subject.")
        return redirect("employees:role_dashboard", role="teacher")
    allocations = list(
        ELearningSubjectAllocation.objects.filter(teacher=employee)
        .select_related("academic_level", "learning_area")
        .order_by(
            "academic_level__order",
            "academic_level__name",
            "learning_area__display_order",
            "learning_area__name",
        )
    )
    elearning_timetable = _teacher_elearning_timetable(employee)
    return render(
        request,
        "employees/teacher_elearning.html",
        {
            "active_nav": "e-learning",
            "teacher_employee": employee,
            "elearning_allocations": allocations,
            "elearning_timetable": elearning_timetable,
            "allocation_count": len(allocations),
            "elearning_pages": TEACHER_ELEARNING_PAGES,
            "elearning_report_pages": TEACHER_ELEARNING_REPORT_PAGES,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def teacher_elearning_page(request, tool):
    denied = _require_teacher_workspace(request)
    if denied:
        return denied
    employee = workspace_view_employee(request)
    has_allocation = ELearningSubjectAllocation.objects.filter(teacher=employee).exists()
    if not has_allocation:
        error(request, "E-learning unlocks when you are allocated an e-learning subject.")
        return redirect("employees:role_dashboard", role="teacher")
    current = _teacher_elearning_page(tool)
    if current is None:
        return redirect("employees:teacher_elearning")
    if current["slug"] == "attendance":
        return teacher_elearning_attendance(request)
    if current["slug"] == "assessments":
        return teacher_elearning_assessments(request)
    if current["slug"] == "learning-materials":
        return teacher_elearning_learning_materials(request, current)
    if current["slug"] in {page["slug"] for page in TEACHER_ELEARNING_REPORT_PAGES}:
        return teacher_elearning_report(request, current)
    return render(
        request,
        "employees/teacher_elearning_page.html",
        {
            "active_nav": "e-learning",
            "active_elearning_tool": current["slug"],
            "page": current,
            "teacher_employee": employee,
            "elearning_pages": TEACHER_ELEARNING_PAGES,
            "elearning_report_pages": TEACHER_ELEARNING_REPORT_PAGES,
        },
    )


@login_required
@require_http_methods(["GET"])
def teacher_elearning_report(request, page):
    denied, employee = _require_teacher_elearning_access(request)
    if denied:
        return denied
    allocations = _teacher_elearning_session_allocations(employee)
    context = _teacher_elearning_report_context(employee, page)
    context["allocations"] = allocations
    context["allocation_count"] = len(allocations)
    context["school_profile"] = SchoolProfile.objects.filter(pk=1).first()

    report_types = (
        ("attendance", "Attendance"),
        ("lesson_plan", "Lesson plan"),
        ("outcome", "Outcome"),
    )
    report_type = (request.GET.get("report_type") or "").strip()
    date_raw = (request.GET.get("report_date") or "").strip()
    generate = (request.GET.get("generate") or "").strip() == "1"
    level_id = _parse_optional_int(request.GET.get("level_id"))
    subject_id = _parse_optional_int(request.GET.get("subject_id"))
    report_date = None
    report_error = ""
    if date_raw:
        try:
            report_date = date.fromisoformat(date_raw)
        except ValueError:
            report_error = "Choose a valid report date."
    elif not generate:
        report_date = date.today()

    scope = _teacher_elearning_report_scope(
        allocations,
        level_id=level_id,
        subject_id=subject_id,
    )
    valid_level_ids = {item["id"] for item in scope["levels"]}
    valid_subject_ids = {
        item["id"]
        for item in scope["subjects"]
        if level_id is None or item["level_id"] == level_id
    }
    if level_id is not None and level_id not in valid_level_ids:
        level_id = None
    if subject_id is not None and subject_id not in valid_subject_ids:
        subject_id = None
    scope = _teacher_elearning_report_scope(
        allocations,
        level_id=level_id,
        subject_id=subject_id,
    )
    scoped_allocations = scope["allocations"]
    allocation_ids = [item.id for item in scoped_allocations]

    selection = {
        "report_date": report_date.isoformat() if report_date else date_raw,
        "report_type": report_type if report_type in {item[0] for item in report_types} else "attendance",
        "level_id": level_id or "",
        "subject_id": subject_id or "",
    }
    context.update(
        {
            "report_types": report_types,
            "selection": selection,
            "report_error": report_error,
            "has_report": False,
            "scope_levels": scope["levels"],
            "scope_subjects": scope["subjects"],
            "scope_catalog": scope["catalog"],
        }
    )

    if not allocations:
        return render(request, "employees/teacher_elearning_report.html", context)

    if not generate:
        return render(request, "employees/teacher_elearning_report.html", context)

    if report_error:
        return render(request, "employees/teacher_elearning_report.html", context)
    if not report_date:
        context["report_error"] = "Select a date for the report."
        return render(request, "employees/teacher_elearning_report.html", context)
    if selection["report_type"] not in {item[0] for item in report_types}:
        context["report_error"] = "Choose attendance, lesson plan, or outcome."
        return render(request, "employees/teacher_elearning_report.html", context)
    if not level_id:
        context["report_error"] = "Select an academic level."
        return render(request, "employees/teacher_elearning_report.html", context)
    if not subject_id:
        context["report_error"] = "Select a subject."
        return render(request, "employees/teacher_elearning_report.html", context)
    if not scoped_allocations:
        context["report_error"] = "That level and subject are not allocated to you."
        return render(request, "employees/teacher_elearning_report.html", context)

    report_type_label = dict(report_types)[selection["report_type"]]
    attendance_rows = []
    lesson_plan_rows = []
    outcome_rows = []
    session_total = 0
    plan_count = 0
    outcome_count = 0
    selected_scope_label = (
        f"{scoped_allocations[0].academic_level.name} · "
        f"{scoped_allocations[0].learning_area.name}"
    )

    if selection["report_type"] == "attendance":
        sessions = list(
            ELearningAttendanceSession.objects.filter(
                allocation_id__in=allocation_ids,
                lesson_date=report_date,
            )
            .select_related(
                "allocation__academic_level",
                "allocation__learning_area",
                "taken_by",
            )
            .prefetch_related(
                Prefetch(
                    "records",
                    queryset=ELearningAttendanceRecord.objects.select_related(
                        "student"
                    ).order_by("student__last_name", "student__first_name"),
                )
            )
            .order_by(
                "allocation__academic_level__order",
                "allocation__learning_area__name",
            )
        )
        for session in sessions:
            counts = {
                ELearningAttendanceRecord.Status.PRESENT: 0,
                ELearningAttendanceRecord.Status.ABSENT: 0,
                ELearningAttendanceRecord.Status.LATE: 0,
                ELearningAttendanceRecord.Status.EXCUSED: 0,
            }
            learners = []
            for record in session.records.all():
                if record.status in counts:
                    counts[record.status] += 1
                learners.append(
                    {
                        "student": record.student,
                        "status": record.status,
                        "status_label": record.get_status_display(),
                    }
                )
            recorded = sum(counts.values())
            present = counts[ELearningAttendanceRecord.Status.PRESENT]
            attendance_rows.append(
                {
                    "session": session,
                    "allocation": session.allocation,
                    "present": present,
                    "absent": counts[ELearningAttendanceRecord.Status.ABSENT],
                    "late": counts[ELearningAttendanceRecord.Status.LATE],
                    "excused": counts[ELearningAttendanceRecord.Status.EXCUSED],
                    "recorded": recorded,
                    "rate": round((present / recorded) * 100) if recorded else None,
                    "learners": learners,
                }
            )
        session_total = len(attendance_rows)

    elif selection["report_type"] == "lesson_plan":
        plans = {
            plan.allocation_id: plan
            for plan in ELearningSubjectLessonPlan.objects.filter(
                allocation_id__in=allocation_ids
            ).select_related("updated_by")
        }
        for allocation in scoped_allocations:
            plan = plans.get(allocation.id)
            has_plan = plan is not None
            if has_plan:
                plan_count += 1
            lesson_plan_rows.append(
                {
                    "allocation": allocation,
                    "plan": plan,
                    "has_plan": has_plan,
                    "strand": (plan.strand if plan else "") or "",
                    "substrand": (plan.substrand if plan else "") or "",
                    "outcomes": (plan.lesson_learning_outcomes if plan else "") or "",
                    "key_inquiry_questions": (plan.key_inquiry_questions if plan else "") or "",
                    "core_competencies": (plan.core_competencies if plan else "") or "",
                    "values": (plan.values if plan else "") or "",
                    "learning_resources": (plan.learning_resources if plan else "") or "",
                    "introduction": (plan.introduction if plan else "") or "",
                    "lesson_development": (plan.lesson_development if plan else "") or "",
                    "updated_at": plan.updated_at if plan else None,
                }
            )

    else:
        outcomes = {
            item.allocation_id: item
            for item in ELearningSubjectOutcome.objects.filter(
                allocation_id__in=allocation_ids
            ).select_related("updated_by")
        }
        for allocation in scoped_allocations:
            outcome = outcomes.get(allocation.id)
            outcome_text = (outcome.outcome if outcome else "") or ""
            has_outcome = bool(outcome_text.strip())
            if has_outcome:
                outcome_count += 1
            outcome_rows.append(
                {
                    "allocation": allocation,
                    "outcome": outcome,
                    "has_outcome": has_outcome,
                    "outcome_text": outcome_text,
                    "updated_at": outcome.updated_at if outcome else None,
                }
            )

    context.update(
        {
            "has_report": True,
            "report_date": report_date,
            "report_type": selection["report_type"],
            "report_type_label": report_type_label,
            "selected_scope_label": selected_scope_label,
            "generated_at": datetime.now(),
            "attendance_rows": attendance_rows,
            "lesson_plan_rows": lesson_plan_rows,
            "outcome_rows": outcome_rows,
            "session_total": session_total,
            "plan_count": plan_count,
            "outcome_count": outcome_count,
            "allocation_count": len(scoped_allocations),
        }
    )
    return render(request, "employees/teacher_elearning_report.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def teacher_elearning_learning_materials(request, page=None):
    denied, employee = _require_teacher_elearning_access(request)
    if denied:
        return denied
    current = page or _teacher_elearning_page("learning-materials")
    allocations_qs = (
        ELearningSubjectAllocation.objects.filter(teacher=employee)
        .select_related("academic_level", "learning_area")
        .order_by(
            "academic_level__order",
            "academic_level__name",
            "learning_area__display_order",
            "learning_area__name",
        )
    )
    allocations = list(allocations_qs)
    form = ELearningLearningMaterialForm(
        request.POST or None,
        request.FILES or None,
        allocations=allocations_qs,
    )
    if request.method == "POST":
        action = (request.POST.get("form_action") or "upload").strip()
        if action == "delete":
            material_id = request.POST.get("material_id")
            material = get_object_or_404(
                ELearningLearningMaterial,
                pk=material_id,
                allocation__teacher=employee,
            )
            if material.cover_image:
                material.cover_image.delete(save=False)
            if material.material_file:
                material.material_file.delete(save=False)
            material.delete()
            success(request, "Learning material removed.")
            return redirect("employees:teacher_elearning_page", tool="learning-materials")
        if form.is_valid():
            form.save(uploaded_by=employee)
            success(request, "Learning material uploaded for student and parent portals.")
            return redirect("employees:teacher_elearning_page", tool="learning-materials")
        error(request, "Check the material details and upload a portal-ready file format.")

    materials = (
        ELearningLearningMaterial.objects.filter(allocation__teacher=employee)
        .select_related("allocation__academic_level", "allocation__learning_area", "uploaded_by")
        .order_by("-created_at", "name")
    )
    categories = sorted({item.category for item in materials if item.category})
    return render(
        request,
        "employees/teacher_elearning_learning_materials.html",
        {
            "active_nav": "e-learning",
            "active_elearning_tool": "learning-materials",
            "page": current,
            "teacher_employee": employee,
            "elearning_pages": TEACHER_ELEARNING_PAGES,
            "elearning_report_pages": TEACHER_ELEARNING_REPORT_PAGES,
            "form": form,
            "materials": materials,
            "allocations": allocations,
            "material_categories": categories,
            "open_upload_modal": bool(form.errors),
            "format_guide": (
                ("Notes/handouts", "PDF"),
                ("Lecture video", "MP4"),
                ("Slides", "PDF or PPTX"),
                ("Quizzes/interactive", "SCORM package (.zip)"),
                ("Audio", "MP3"),
            ),
        },
    )


@login_required
@require_http_methods(["GET"])
def teacher_elearning_material_download(request, material_id):
    denied, employee = _require_teacher_elearning_access(request)
    if denied:
        return denied
    material = get_object_or_404(
        ELearningLearningMaterial,
        pk=material_id,
        allocation__teacher=employee,
    )
    return material.open_download_response()


@login_required
@require_http_methods(["GET"])
def teacher_elearning_material_view(request, material_id):
    denied, employee = _require_teacher_elearning_access(request)
    if denied:
        return denied
    material = get_object_or_404(
        ELearningLearningMaterial,
        pk=material_id,
        allocation__teacher=employee,
    )
    return material.open_view_response()


def _elearning_material_file_response(material):
    return material.open_download_response()


@login_required
@require_http_methods(["GET"])
def teacher_elearning_attendance(request):
    denied, employee = _require_teacher_elearning_access(request)
    if denied:
        return denied
    level_groups = _teacher_elearning_allocated_levels(employee)
    subject_count = sum(group["subject_count"] for group in level_groups)
    return render(
        request,
        "employees/teacher_elearning_attendance.html",
        {
            "active_nav": "e-learning",
            "active_elearning_tool": "attendance",
            "elearning_pages": TEACHER_ELEARNING_PAGES,
            "elearning_report_pages": TEACHER_ELEARNING_REPORT_PAGES,
            "level_groups": level_groups,
            "subject_count": subject_count,
            "level_count": len(level_groups),
        },
    )


@login_required
@require_http_methods(["GET"])
def teacher_elearning_attendance_level(request, level_id):
    denied, employee = _require_teacher_elearning_access(request)
    if denied:
        return denied
    allocations, academic_level, _allocation = _teacher_elearning_allocation_or_redirect(
        employee, level_id
    )
    if not allocations:
        error(request, "That academic level is not allocated to you for e-learning.")
        return redirect("employees:teacher_elearning_page", tool="attendance")

    allocated_levels = [
        group["level"] for group in _teacher_elearning_allocated_levels(employee)
    ]
    allocation_ids = [item.id for item in allocations]
    plan_ids = set(
        ELearningSubjectLessonPlan.objects.filter(allocation_id__in=allocation_ids).values_list(
            "allocation_id", flat=True
        )
    )
    outcome_ids = set(
        ELearningSubjectOutcome.objects.filter(allocation_id__in=allocation_ids).values_list(
            "allocation_id", flat=True
        )
    )
    attendance_ids = set(
        ELearningAttendanceSession.objects.filter(allocation_id__in=allocation_ids)
        .values_list("allocation_id", flat=True)
        .distinct()
    )
    for item in allocations:
        item.has_lesson_plan = item.id in plan_ids
        item.has_outcome = item.id in outcome_ids
        item.has_attendance = item.id in attendance_ids
    return render(
        request,
        "employees/teacher_elearning_attendance_level.html",
        {
            "active_nav": "e-learning",
            "active_elearning_tool": "attendance",
            "elearning_pages": TEACHER_ELEARNING_PAGES,
            "elearning_report_pages": TEACHER_ELEARNING_REPORT_PAGES,
            "selected_level": academic_level,
            "allocations": allocations,
            "allocated_levels": allocated_levels,
            "teacher_elearning_attendance_home_url": reverse(
                "employees:teacher_elearning_page", kwargs={"tool": "attendance"}
            ),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def teacher_elearning_attendance_profile(request, level_id, subject_id):
    denied, employee = _require_teacher_elearning_access(request)
    if denied:
        return denied
    allocations, academic_level, allocation = _teacher_elearning_allocation_or_redirect(
        employee, level_id, subject_id
    )
    if allocation is None:
        error(request, "That subject is not allocated to you for e-learning on this level.")
        return redirect("employees:teacher_elearning_page", tool="attendance")

    profile_url = reverse(
        "employees:teacher_elearning_attendance_profile",
        kwargs={"level_id": academic_level.id, "subject_id": allocation.learning_area_id},
    )
    students = list(_students_in_academic_level(academic_level))
    lesson_plan = ELearningSubjectLessonPlan.objects.filter(allocation=allocation).first()
    subject_outcome = ELearningSubjectOutcome.objects.filter(allocation=allocation).first()

    lesson_date_raw = (request.POST.get("lesson_date") if request.method == "POST" else None) or (
        request.GET.get("date") or ""
    ).strip()
    try:
        lesson_date = date.fromisoformat(lesson_date_raw) if lesson_date_raw else date.today()
    except ValueError:
        lesson_date = date.today()

    if request.method == "POST":
        action = (request.POST.get("form_action") or "").strip()
        if action == "lesson_plan":
            ELearningSubjectLessonPlan.objects.update_or_create(
                allocation=allocation,
                defaults={
                    "strand": (request.POST.get("strand") or "").strip()[:255],
                    "substrand": (request.POST.get("substrand") or "").strip()[:255],
                    "lesson_learning_outcomes": (
                        request.POST.get("lesson_learning_outcomes") or ""
                    ).strip(),
                    "key_inquiry_questions": (
                        request.POST.get("key_inquiry_questions") or ""
                    ).strip(),
                    "core_competencies": (request.POST.get("core_competencies") or "").strip(),
                    "values": (request.POST.get("values") or "").strip(),
                    "pcis": (request.POST.get("pcis") or "").strip(),
                    "learning_resources": (request.POST.get("learning_resources") or "").strip(),
                    "organization_of_learning": (
                        request.POST.get("organization_of_learning") or ""
                    ).strip(),
                    "introduction": (request.POST.get("introduction") or "").strip(),
                    "lesson_development": (request.POST.get("lesson_development") or "").strip(),
                    "updated_by": employee,
                },
            )
            success(request, "Lesson plan saved.")
            return redirect(f"{profile_url}#lesson-plan")
        if action == "outcome":
            ELearningSubjectOutcome.objects.update_or_create(
                allocation=allocation,
                defaults={
                    "outcome": (request.POST.get("outcome") or "").strip(),
                    "updated_by": employee,
                },
            )
            success(request, "E-learning subject outcome saved.")
            return redirect(f"{profile_url}?date={lesson_date.isoformat()}#outcome")
        if action == "attendance":
            session, _created = ELearningAttendanceSession.objects.update_or_create(
                allocation=allocation,
                lesson_date=lesson_date,
                defaults={
                    "notes": (request.POST.get("attendance_notes") or "").strip(),
                    "taken_by": employee,
                },
            )
            valid_statuses = {choice for choice, _label in ELearningAttendanceRecord.Status.choices}
            student_ids = {student.id for student in students}
            bulk_upsert_by_keys(
                ELearningAttendanceRecord,
                scope_filter={"session_id": session.id},
                create_defaults={"session_id": session.id},
                rows=[
                    {
                        "student_id": student.id,
                        "status": (
                            (request.POST.get(f"status_{student.id}") or "").strip().upper()
                            if (request.POST.get(f"status_{student.id}") or "").strip().upper()
                            in valid_statuses
                            else ELearningAttendanceRecord.Status.PRESENT
                        ),
                    }
                    for student in students
                ],
                key_fields=("student_id",),
                update_fields=("status",),
            )
            ELearningAttendanceRecord.objects.filter(session=session).exclude(
                student_id__in=student_ids
            ).delete()
            success(request, f"Attendance saved for {lesson_date.strftime('%d %b %Y')}.")
            return redirect(f"{profile_url}?date={lesson_date.isoformat()}#attendance")
        error(request, "Unknown form action.")
        return redirect(profile_url)

    attendance_session = ELearningAttendanceSession.objects.filter(
        allocation=allocation, lesson_date=lesson_date
    ).first()
    status_lookup = {}
    if attendance_session:
        status_lookup = {
            record.student_id: record.status for record in attendance_session.records.all()
        }
    for student in students:
        student.attendance_status = status_lookup.get(
            student.id, ELearningAttendanceRecord.Status.PRESENT
        )

    allocated_levels = [
        group["level"] for group in _teacher_elearning_allocated_levels(employee)
    ]
    return render(
        request,
        "employees/teacher_elearning_attendance_profile.html",
        {
            "active_nav": "e-learning",
            "active_elearning_tool": "attendance",
            "elearning_pages": TEACHER_ELEARNING_PAGES,
            "elearning_report_pages": TEACHER_ELEARNING_REPORT_PAGES,
            "selected_level": academic_level,
            "allocation": allocation,
            "subject": allocation.learning_area,
            "allocations": allocations,
            "allocated_levels": allocated_levels,
            "teacher_elearning_attendance_home_url": reverse(
                "employees:teacher_elearning_page", kwargs={"tool": "attendance"}
            ),
            "students": students,
            "lesson_plan": lesson_plan,
            "subject_outcome": subject_outcome,
            "lesson_date": lesson_date,
            "attendance_session": attendance_session,
            "attendance_statuses": ELearningAttendanceRecord.Status.choices,
        },
    )


def _teacher_elearning_subjects(employee, level):
    allocated_ids = list(
        ELearningSubjectAllocation.objects.filter(teacher=employee, academic_level=level)
        .order_by("learning_area__display_order", "learning_area__name")
        .values_list("learning_area_id", flat=True)
    )
    if not allocated_ids:
        return []
    exam_subjects = _exam_record_subjects(level)
    exam_by_id = {subject.id: subject for subject in exam_subjects}
    subjects = [exam_by_id[subject_id] for subject_id in allocated_ids if subject_id in exam_by_id]
    missing_ids = [subject_id for subject_id in allocated_ids if subject_id not in exam_by_id]
    if missing_ids:
        extras = list(
            LearningArea.objects.filter(id__in=missing_ids).order_by("display_order", "name")
        )
        extra_order = {subject_id: index for index, subject_id in enumerate(allocated_ids)}
        extras.sort(key=lambda subject: extra_order.get(subject.id, 99))
        subjects.extend(extras)
    return subjects


def _elearning_assessment_mark_lookup(assessment, students, subjects):
    if not students or not subjects:
        return {}
    return {
        (mark.student_id, mark.learning_area_id): {
            "marks": mark.marks,
            "out_of_marks": mark.out_of_marks,
        }
        for mark in ELearningAssessmentMark.objects.filter(
            assessment=assessment,
            student_id__in=[student.id for student in students],
            learning_area_id__in=[subject.id for subject in subjects],
        )
    }


def _save_elearning_assessment_marks(assessment, students, subjects, out_of_by_subject, post_data):
    to_upsert = []
    to_delete = []
    for student in students:
        for subject in subjects:
            raw = (post_data.get(f"mark_{student.id}_{subject.id}") or "").strip()
            if raw == "":
                to_delete.append((student.id, subject.id))
                continue
            marks = int(raw)
            limit = out_of_by_subject.get(subject.id, subject.total_marks)
            if marks < 0 or marks > limit:
                raise ValidationError(f"Marks must be a whole number out of {limit}.")
            to_upsert.append((student.id, subject.id, marks, limit))
    with transaction.atomic():
        if to_delete:
            query = Q()
            for student_id, subject_id in to_delete:
                query |= Q(student_id=student_id, learning_area_id=subject_id)
            ELearningAssessmentMark.objects.filter(assessment=assessment).filter(query).delete()
        bulk_upsert_by_keys(
            ELearningAssessmentMark,
            scope_filter={"assessment_id": assessment.id},
            create_defaults={"assessment_id": assessment.id},
            rows=[
                {
                    "student_id": student_id,
                    "learning_area_id": subject_id,
                    "marks": marks,
                    "out_of_marks": out_of,
                }
                for student_id, subject_id, marks, out_of in to_upsert
            ],
            key_fields=("student_id", "learning_area_id"),
            update_fields=("marks", "out_of_marks"),
        )


def _grouped_elearning_assessments():
    assessments = list(
        ELearningAssessment.objects.select_related("academic_year", "academic_term")
        .annotate(mark_count=Count("marks", distinct=True))
        .order_by(
            "-academic_year__is_current",
            "-academic_year__start_date",
            "academic_year__name",
            "-academic_term__order",
            "-created_at",
            "name",
        )
    )
    grouped = OrderedDict()
    for assessment in assessments:
        year = assessment.academic_year
        key = year.id if year else 0
        group = grouped.setdefault(key, {"year": year, "assessments": []})
        group["assessments"].append(assessment)
    return list(grouped.values())


@login_required
@require_http_methods(["GET", "POST"])
def teacher_elearning_assessments(request):
    denied, employee = _require_teacher_elearning_access(request)
    if denied:
        return denied

    years = _academic_calendar_years()
    year_by_id = {year.id: year for year in years}
    default_year = next((year for year in years if year.is_current), None) or (
        years[0] if years else None
    )
    default_terms = list(default_year.terms.all()) if default_year else []
    default_term = next((term for term in default_terms if term.is_current), None) or (
        default_terms[0] if default_terms else None
    )

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()[:120]
        year_raw = (request.POST.get("academic_year_id") or "").strip()
        term_raw = (request.POST.get("academic_term_id") or "").strip()
        selected_year = year_by_id.get(int(year_raw)) if year_raw.isdigit() else None
        selected_term = None
        if selected_year and term_raw.isdigit():
            selected_term = next(
                (term for term in selected_year.terms.all() if term.id == int(term_raw)),
                None,
            )
        if not name or selected_year is None or selected_term is None:
            error(request, "Enter an assessment name and choose the academic year and term.")
        else:
            assessment = ELearningAssessment.objects.create(
                name=name,
                academic_year=selected_year,
                academic_term=selected_term,
                created_by=employee,
            )
            success(request, f"{assessment.display_name} was registered.")
            return redirect(
                "employees:teacher_elearning_assessment_detail",
                assessment_id=assessment.id,
            )

    assessment_groups = _grouped_elearning_assessments()
    assessment_count = sum(len(group["assessments"]) for group in assessment_groups)
    year_terms = [
        {
            "id": year.id,
            "name": year.name,
            "terms": [
                {"id": term.id, "name": term.name, "is_current": term.is_current}
                for term in year.terms.all()
            ],
        }
        for year in years
    ]
    return render(
        request,
        "employees/teacher_elearning_assessments.html",
        {
            "active_nav": "e-learning",
            "active_elearning_tool": "assessments",
            "elearning_pages": TEACHER_ELEARNING_PAGES,
            "elearning_report_pages": TEACHER_ELEARNING_REPORT_PAGES,
            "assessment_groups": assessment_groups,
            "assessment_count": assessment_count,
            "academic_years": years,
            "default_year": default_year,
            "default_term": default_term,
            "default_terms": default_terms,
            "year_terms": year_terms,
        },
    )


def _teacher_elearning_assessment_classes(employee):
    """Active classes under levels where this teacher has e-learning subject allocations."""
    level_ids = list(
        ELearningSubjectAllocation.objects.filter(teacher=employee)
        .values_list("academic_level_id", flat=True)
        .distinct()
    )
    if not level_ids:
        return []
    return list(
        AcademicClass.objects.filter(
            academic_level_id__in=level_ids,
            status=AcademicClass.Status.ACTIVE,
            academic_level__status=AcademicLevel.Status.ACTIVE,
        )
        .select_related("academic_level")
        .order_by("academic_level__order", "academic_level__name", "order", "name")
    )


@login_required
@require_http_methods(["GET", "POST"])
def teacher_elearning_assessment_detail(request, assessment_id, class_id=None):
    denied, employee = _require_teacher_elearning_access(request)
    if denied:
        return denied
    assessment = get_object_or_404(
        ELearningAssessment.objects.select_related("academic_year", "academic_term"),
        pk=assessment_id,
    )
    assessment_classes = _teacher_elearning_assessment_classes(employee)
    selected_class = None
    selected_level = None
    students = []
    subjects = []
    subject_means = []
    out_of_settings_changed = False

    if class_id is not None:
        selected_class = next((item for item in assessment_classes if item.id == class_id), None)
        if selected_class is None:
            error(request, "That class is not available for your e-learning allocations.")
            return redirect(
                "employees:teacher_elearning_assessment_detail",
                assessment_id=assessment.id,
            )
        selected_level = (
            AcademicLevel.objects.prefetch_related(
                Prefetch(
                    "learning_areas",
                    queryset=LearningArea.objects.filter(status=LearningArea.Status.ACTIVE).order_by(
                        "display_order", "name"
                    ),
                ),
                "exam_subject_settings",
            ).get(pk=selected_class.academic_level_id)
        )
        students = list(_students_in_academic_level(selected_level, selected_class))
        subjects = _teacher_elearning_subjects(employee, selected_level)
        out_of_by_subject = _exam_record_out_of(selected_level, subjects)
        for subject in subjects:
            subject.exam_out_of = out_of_by_subject.get(subject.id, subject.total_marks)
        class_url = reverse(
            "employees:teacher_elearning_assessment_class",
            kwargs={"assessment_id": assessment.id, "class_id": selected_class.id},
        )
        if request.method == "POST":
            try:
                _save_elearning_assessment_marks(
                    assessment,
                    students,
                    subjects,
                    out_of_by_subject,
                    request.POST,
                )
            except (TypeError, ValueError, ValidationError):
                error(request, "Enter whole numbers within each subject's total marks.")
                _attach_exam_mark_cells(
                    students,
                    subjects,
                    {
                        (student.id, subject.id): (
                            request.POST.get(f"mark_{student.id}_{subject.id}") or ""
                        ).strip()
                        for student in students
                        for subject in subjects
                    },
                    out_of_by_subject,
                )
                subject_means = _exam_record_subject_means(students, subjects)
            else:
                success(request, "E-learning assessment marks were saved.")
                return redirect(class_url)
        else:
            marks_lookup = _elearning_assessment_mark_lookup(assessment, students, subjects)
            out_of_settings_changed = _exam_marks_out_of_settings_changed(
                marks_lookup, out_of_by_subject
            )
            _attach_exam_mark_cells(
                students,
                subjects,
                marks_lookup,
                out_of_by_subject,
            )
            subject_means = _exam_record_subject_means(students, subjects)

    class_groups = OrderedDict()
    for academic_class in assessment_classes:
        level = academic_class.academic_level
        group = class_groups.setdefault(level.id, {"level": level, "classes": []})
        group["classes"].append(academic_class)

    return render(
        request,
        "employees/teacher_elearning_assessment_detail.html",
        {
            "active_nav": "e-learning",
            "active_elearning_tool": "assessments",
            "elearning_pages": TEACHER_ELEARNING_PAGES,
            "elearning_report_pages": TEACHER_ELEARNING_REPORT_PAGES,
            "assessment": assessment,
            "assessment_title": assessment.display_name,
            "assessment_classes": assessment_classes,
            "class_groups": list(class_groups.values()),
            "selected_class": selected_class,
            "selected_level": selected_level,
            "students": students,
            "subjects": subjects,
            "subject_means": subject_means,
            "out_of_settings_changed": out_of_settings_changed,
            "teacher_elearning_assessment_home_url": reverse(
                "employees:teacher_elearning_assessment_detail",
                kwargs={"assessment_id": assessment.id},
            ),
        },
    )


@login_required
@require_http_methods(["GET"])
def teacher_my_class(request):
    denied = _require_teacher_workspace(request)
    if denied:
        return denied
    employee = workspace_view_employee(request)
    led_classes = _teacher_led_classes(employee)
    if not led_classes:
        error(request, "My class unlocks when you are allocated as a class teacher.")
        return redirect("employees:role_dashboard", role="teacher")
    class_groups = []
    for academic_class in led_classes:
        students = list(_students_in_academic_level(academic_class.academic_level, academic_class))
        class_groups.append(
            {
                "academic_class": academic_class,
                "students": students,
                "student_count": len(students),
            }
        )
    return render(
        request,
        "employees/teacher_my_class.html",
        {
            "active_nav": "my-class",
            "teacher_employee": employee,
            "class_groups": class_groups,
            "class_count": len(class_groups),
            "my_class_pages": TEACHER_MY_CLASS_PAGES,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def teacher_my_class_page(request, tool):
    denied = _require_teacher_workspace(request)
    if denied:
        return denied
    employee = workspace_view_employee(request)
    led_classes = _teacher_led_classes(employee)
    if not led_classes:
        error(request, "My class unlocks when you are allocated as a class teacher.")
        return redirect("employees:role_dashboard", role="teacher")
    current = _teacher_my_class_page(tool)
    if current is None:
        return redirect("employees:teacher_my_class")
    if current["slug"] == "register-class-attendance":
        return teacher_register_class_attendance(request, employee, led_classes, current)
    if current["slug"] == "students-class-attendance":
        return teacher_students_class_attendance_analytics(
            request, employee, led_classes, current
        )
    return render(
        request,
        "employees/teacher_my_class_page.html",
        {
            "active_nav": "my-class",
            "active_my_class_tool": current["slug"],
            "page": current,
            "teacher_employee": employee,
            "led_classes": led_classes,
            "class_count": len(led_classes),
        },
    )


def teacher_register_class_attendance(request, employee, led_classes, page):
    selected_class = led_classes[0]
    raw_class_id = (
        request.POST.get("class_id") if request.method == "POST" else request.GET.get("class_id")
    ) or ""
    if raw_class_id:
        try:
            class_id = int(raw_class_id)
        except (TypeError, ValueError):
            class_id = None
        else:
            selected_class = next((item for item in led_classes if item.id == class_id), selected_class)

    date_raw = (
        (request.POST.get("attendance_date") if request.method == "POST" else request.GET.get("date"))
        or ""
    ).strip()
    try:
        attendance_date = date.fromisoformat(date_raw) if date_raw else date.today()
    except ValueError:
        attendance_date = date.today()

    sort_mode = _resolve_student_sort(request)
    students = _sorted_students(
        list(
            _students_in_academic_level(
                selected_class.academic_level,
                selected_class,
                sort=sort_mode,
            )
        ),
        sort_mode,
    )

    if request.method == "POST":
        session, _created = ClassAttendanceSession.objects.update_or_create(
            academic_class=selected_class,
            attendance_date=attendance_date,
            defaults={
                "notes": (request.POST.get("attendance_notes") or "").strip(),
                "taken_by": employee,
            },
        )
        student_ids = {student.id for student in students}
        bulk_upsert_by_keys(
            ClassAttendanceRecord,
            scope_filter={"session_id": session.id},
            create_defaults={"session_id": session.id},
            rows=[
                {
                    "student_id": student.id,
                    "morning": request.POST.get(f"morning_{student.id}") == "on",
                    "afternoon": request.POST.get(f"afternoon_{student.id}") == "on",
                    "evening": request.POST.get(f"evening_{student.id}") == "on",
                }
                for student in students
            ],
            key_fields=("student_id",),
            update_fields=("morning", "afternoon", "evening"),
        )
        ClassAttendanceRecord.objects.filter(session=session).exclude(student_id__in=student_ids).delete()
        success(
            request,
            f"Class attendance saved for {selected_class.display_label} on {attendance_date.strftime('%d %b %Y')}.",
        )
        sort_mode = _resolve_student_sort(request)
        return redirect(
            _with_student_sort(
                f"{reverse('employees:teacher_my_class_page', kwargs={'tool': 'register-class-attendance'})}"
                f"?class_id={selected_class.id}&date={attendance_date.isoformat()}",
                sort_mode,
            )
        )

    attendance_session = (
        ClassAttendanceSession.objects.filter(
            academic_class=selected_class,
            attendance_date=attendance_date,
        )
        .prefetch_related("records")
        .first()
    )
    record_lookup = {}
    if attendance_session:
        record_lookup = {record.student_id: record for record in attendance_session.records.all()}
    for student in students:
        record = record_lookup.get(student.id)
        student.morning = bool(record and record.morning)
        student.afternoon = bool(record and record.afternoon)
        student.evening = bool(record and record.evening)

    return render(
        request,
        "employees/teacher_my_class_students_attendance.html",
        {
            "active_nav": "my-class",
            "active_my_class_tool": "register-class-attendance",
            "page": page,
            "teacher_employee": employee,
            "led_classes": led_classes,
            "class_count": len(led_classes),
            "selected_class": selected_class,
            "students": students,
            "attendance_date": attendance_date,
            "attendance_session": attendance_session,
            "present_morning": sum(1 for student in students if student.morning),
            "present_afternoon": sum(1 for student in students if student.afternoon),
            "present_evening": sum(1 for student in students if student.evening),
            **_student_sort_template_context(request),
        },
    )


def _class_attendance_session_cell(present, recorded, session_total, is_day, day_present=None):
    if is_day:
        if day_present is None:
            return {
                "is_range": False,
                "status": None,
                "status_label": "—",
                "display": "—",
                "rate_class": "is-empty",
                "title": "No class attendance recorded for this day",
            }
        label = "Present" if day_present else "Absent"
        return {
            "is_range": False,
            "status": "PRESENT" if day_present else "ABSENT",
            "status_label": label,
            "display": label,
            "rate_class": "status-present" if day_present else "status-absent",
            "title": label,
        }
    if recorded:
        pct = round((present / recorded) * 100)
        if pct >= 80:
            rate_class = "rate-high"
        elif pct >= 50:
            rate_class = "rate-mid"
        else:
            rate_class = "rate-low"
        return {
            "is_range": True,
            "status": None,
            "status_label": f"{pct}%",
            "display": f"{pct}%",
            "rate_class": rate_class,
            "title": f"{present} present of {recorded} recorded ({pct}%)",
            "percent": pct,
            "present": present,
            "recorded": recorded,
        }
    return {
        "is_range": True,
        "status": None,
        "status_label": "—",
        "display": "—",
        "rate_class": "is-empty",
        "title": (
            f"{session_total} class day(s) recorded, but not for this student"
            if session_total
            else "No class attendance recorded in this range"
        ),
    }


def teacher_students_class_attendance_analytics(request, employee, led_classes, page):
    selected_class = led_classes[0]
    raw_class_id = (request.GET.get("class_id") or "").strip()
    if raw_class_id:
        try:
            class_id = int(raw_class_id)
        except (TypeError, ValueError):
            class_id = None
        else:
            selected_class = next((item for item in led_classes if item.id == class_id), selected_class)

    filter_ctx = _resolve_subject_attendance_filter(request)
    if filter_ctx["is_day_scope"]:
        filter_ctx["filter_subtitle"] = (
            "One day at a time. See morning, afternoon, and evening status for each student."
        )
    else:
        filter_ctx["filter_subtitle"] = (
            f"{filter_ctx['range_start'].strftime('%d %b %Y')} – "
            f"{filter_ctx['range_end'].strftime('%d %b %Y')}. "
            "Cells show attendance percentage for each session."
        )
    sort_mode = _resolve_student_sort(request)
    students = _sorted_students(
        list(
            _students_in_academic_level(
                selected_class.academic_level,
                selected_class,
                sort=sort_mode,
            )
        ),
        sort_mode,
    )
    sessions = list(
        ClassAttendanceSession.objects.filter(
            academic_class=selected_class,
            attendance_date__gte=filter_ctx["range_start"],
            attendance_date__lte=filter_ctx["range_end"],
        ).prefetch_related("records")
    )
    session_total = len(sessions)
    tallies = {
        student.id: {
            "morning_present": 0,
            "afternoon_present": 0,
            "evening_present": 0,
            "recorded": 0,
            "day_morning": None,
            "day_afternoon": None,
            "day_evening": None,
        }
        for student in students
    }
    for session in sessions:
        for record in session.records.all():
            bucket = tallies.get(record.student_id)
            if bucket is None:
                continue
            bucket["recorded"] += 1
            if record.morning:
                bucket["morning_present"] += 1
            if record.afternoon:
                bucket["afternoon_present"] += 1
            if record.evening:
                bucket["evening_present"] += 1
            if filter_ctx["is_day_scope"]:
                bucket["day_morning"] = bool(record.morning)
                bucket["day_afternoon"] = bool(record.afternoon)
                bucket["day_evening"] = bool(record.evening)

    student_rows = []
    for student in students:
        bucket = tallies[student.id]
        student_rows.append(
            {
                "student": student,
                "morning": _class_attendance_session_cell(
                    bucket["morning_present"],
                    bucket["recorded"],
                    session_total,
                    not filter_ctx["show_percentages"],
                    bucket["day_morning"],
                ),
                "afternoon": _class_attendance_session_cell(
                    bucket["afternoon_present"],
                    bucket["recorded"],
                    session_total,
                    not filter_ctx["show_percentages"],
                    bucket["day_afternoon"],
                ),
                "evening": _class_attendance_session_cell(
                    bucket["evening_present"],
                    bucket["recorded"],
                    session_total,
                    not filter_ctx["show_percentages"],
                    bucket["day_evening"],
                ),
            }
        )

    return render(
        request,
        "employees/teacher_my_class_students_attendance_analytics.html",
        {
            "active_nav": "my-class",
            "active_my_class_tool": "students-class-attendance",
            "page": page,
            "teacher_employee": employee,
            "led_classes": led_classes,
            "class_count": len(led_classes),
            "selected_class": selected_class,
            "students": students,
            "student_rows": student_rows,
            "session_total": session_total,
            **filter_ctx,
            **_student_sort_template_context(request),
        },
    )


def _registered_exams_latest():
    generations = list(
        GeneratedExamTimetable.objects.select_related("academic_year", "academic_term")
        .annotate(sitting_count=Count("sittings", distinct=True))
        .order_by("-created_at", "-id")
    )
    for exam in generations:
        _annotate_exam_workflow_flags(exam)
    return generations, len(generations), _current_exam_for_dashboard()


@login_required
def teacher_exam_records(request):
    denied = _require_teacher_workspace(request)
    if denied:
        return denied
    exams, exam_count, current_exam = _registered_exams_latest()
    return render(
        request,
        "employees/teacher_exam_records.html",
        {
            "active_nav": "exam-records",
            "exams": exams,
            "exam_count": exam_count,
            "current_exam": current_exam,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def teacher_exam_record_detail(request, exam_id, class_id=None):
    denied = _require_teacher_workspace(request)
    if denied:
        return denied
    generation = get_object_or_404(
        GeneratedExamTimetable.objects.select_related("academic_year", "academic_term"),
        pk=exam_id,
    )
    employee = workspace_view_employee(request)
    exam_subject_groups = _teacher_exam_subject_groups(employee, generation)
    exam_subject_allocations = [
        item for group in exam_subject_groups for item in group["subjects"]
    ]
    exam_class_groups = _teacher_exam_class_groups(employee, generation)
    exam_classes = [academic_class for group in exam_class_groups for academic_class in group["classes"]]
    selected_class = None
    selected_level = None
    students = []
    subjects = []
    subject_means = []
    out_of_settings_changed = False
    if class_id is not None:
        selected_class = next((item for item in exam_classes if item.id == class_id), None)
        if selected_class is None:
            return redirect("employees:teacher_exam_record_detail", exam_id=generation.id)
        selected_level = selected_class.academic_level
        sort_mode = _resolve_student_sort(request)
        students = _sorted_students(
            list(_students_in_academic_level(selected_level, selected_class, sort=sort_mode)),
            sort_mode,
        )
        subjects = _teacher_class_subjects(
            employee, selected_class, selected_level
        )
        out_of_by_subject = _exam_record_out_of(selected_level, subjects)
        for subject in subjects:
            subject.exam_out_of = out_of_by_subject.get(subject.id, subject.total_marks)
        class_url = reverse(
            "employees:teacher_exam_record_class",
            kwargs={"exam_id": generation.id, "class_id": selected_class.id},
        )
        marks_editable = generation.status == GeneratedExamTimetable.Status.MARKING
        if request.method == "POST":
            if not marks_editable:
                error(
                    request,
                    "Marks can only be edited while this assessment is in Marking status.",
                )
            else:
                try:
                    _save_exam_record_marks(
                        generation,
                        students,
                        subjects,
                        out_of_by_subject,
                        request.POST,
                        input_is_percent=False,
                    )
                except (TypeError, ValueError, ValidationError):
                    error(request, "Enter whole numbers within each subject's total marks.")
                    _attach_exam_mark_cells(
                        students,
                        subjects,
                        {
                            (student.id, subject.id): (
                                request.POST.get(f"mark_{student.id}_{subject.id}") or ""
                            ).strip()
                            for student in students
                            for subject in subjects
                        },
                        out_of_by_subject,
                    )
                    subject_means = _exam_record_subject_means(students, subjects)
                else:
                    success(request, "Student marks were saved.")
                    return redirect(_with_student_sort(class_url, sort_mode))
            marks_lookup = _exam_record_mark_lookup(generation, students, subjects)
            out_of_settings_changed = _exam_marks_out_of_settings_changed(
                marks_lookup, out_of_by_subject
            )
            _attach_exam_mark_cells(
                students,
                subjects,
                marks_lookup,
                out_of_by_subject,
            )
            subject_means = _exam_record_subject_means(students, subjects)
        else:
            marks_lookup = _exam_record_mark_lookup(generation, students, subjects)
            out_of_settings_changed = _exam_marks_out_of_settings_changed(
                marks_lookup, out_of_by_subject
            )
            _attach_exam_mark_cells(
                students,
                subjects,
                marks_lookup,
                out_of_by_subject,
            )
            subject_means = _exam_record_subject_means(students, subjects)
    else:
        marks_editable = generation.status == GeneratedExamTimetable.Status.MARKING
    return render(
        request,
        "employees/teacher_exam_record_detail.html",
        {
            "active_nav": "exam-records",
            "active_teacher_exam_nav": "class" if selected_class else None,
            "exam": generation,
            "exam_title": _exam_record_title(generation),
            "teacher_exam_home_url": reverse(
                "employees:teacher_exam_record_detail", kwargs={"exam_id": generation.id}
            ),
            "exam_classes": exam_classes,
            "exam_subject_groups": exam_subject_groups,
            "exam_subject_allocations": exam_subject_allocations,
            "selected_class": selected_class,
            "selected_level": selected_level,
            "students": students,
            "subjects": subjects,
            "subject_means": subject_means,
            "out_of_settings_changed": out_of_settings_changed,
            "marks_editable": marks_editable,
            **(_student_sort_template_context(request) if selected_class else {}),
        },
    )


def _exam_active_classes(generation):
    return list(
        AcademicClass.objects.filter(
            status=AcademicClass.Status.ACTIVE,
            academic_level_id__in=generation.academic_levels.values_list("id", flat=True),
        )
        .select_related("academic_level")
        .order_by("academic_level__order", "academic_level__name", "order", "name")
    )


def _teacher_exam_analytics_class_result(generation, academic_class, *, is_allocated=True):
    level = academic_class.academic_level
    students = list(_students_in_academic_level(level, academic_class))
    subjects = _exam_record_subjects(level, academic_class)
    out_of_by_subject = _exam_record_out_of(level, subjects)
    for subject in subjects:
        subject.exam_out_of = out_of_by_subject.get(subject.id, subject.total_marks)
    _attach_exam_mark_cells(
        students,
        subjects,
        _exam_record_mark_lookup(generation, students, subjects),
        out_of_by_subject,
    )
    return {
        "academic_class": academic_class,
        "students": students,
        "subjects": subjects,
        "subject_means": _exam_record_subject_means(students, subjects),
        "is_allocated": is_allocated,
    }


@login_required
@require_http_methods(["GET"])
def teacher_exam_analytics(request, exam_id, class_id=None, view_all=False):
    denied = _require_teacher_workspace(request)
    if denied:
        return denied
    generation = get_object_or_404(
        GeneratedExamTimetable.objects.select_related("academic_year", "academic_term"),
        pk=exam_id,
    )
    employee = workspace_view_employee(request)
    exam_classes = _teacher_exam_classes(employee, generation)
    exam_class_groups = _teacher_exam_class_groups(employee, generation)
    exam_subject_groups = _teacher_exam_subject_groups(employee, generation)
    exam_subject_allocations = [
        item for group in exam_subject_groups for item in group["subjects"]
    ]
    allocated_ids = {item.id for item in exam_classes}
    other_classes = [
        academic_class
        for academic_class in _exam_active_classes(generation)
        if academic_class.id not in allocated_ids
    ]
    selected_class = None
    class_results = []
    if view_all:
        class_results = [
            _teacher_exam_analytics_class_result(generation, academic_class, is_allocated=True)
            for academic_class in exam_classes
        ]
    elif class_id is not None:
        selected_class = next((item for item in exam_classes if item.id == class_id), None)
        is_allocated = selected_class is not None
        if selected_class is None:
            selected_class = next((item for item in other_classes if item.id == class_id), None)
        if selected_class is None:
            return redirect("employees:teacher_exam_analytics", exam_id=generation.id)
        class_results = [
            _teacher_exam_analytics_class_result(
                generation, selected_class, is_allocated=is_allocated
            )
        ]
    return render(
        request,
        "employees/teacher_exam_analytics.html",
        {
            "active_nav": "exam-records",
            "active_teacher_exam_nav": "analytics",
            "exam": generation,
            "exam_title": _exam_record_title(generation),
            "teacher_exam_home_url": reverse(
                "employees:teacher_exam_record_detail", kwargs={"exam_id": generation.id}
            ),
            "exam_classes": exam_classes,
            "exam_class_groups": exam_class_groups,
            "exam_subject_allocations": exam_subject_allocations,
            "other_classes": other_classes,
            "selected_class": selected_class,
            "view_all_classes": view_all,
            "class_results": class_results,
        },
    )


def _teacher_allocated_classes(employee):
    classes = []
    for group in _teacher_allocated_levels(employee):
        for academic_class in group["classes"]:
            academic_class.level_name = group["level"].name
            classes.append(academic_class)
    return classes


def _teacher_class_allocations(employee, academic_class):
    return list(
        ClassSubjectAllocation.objects.filter(teacher=employee, academic_class=academic_class)
        .select_related("learning_area", "academic_class", "academic_class__academic_level")
        .order_by("learning_area__display_order", "learning_area__name")
    )


def _teacher_allocation_or_redirect(employee, class_id, subject_id=None):
    academic_class = get_object_or_404(
        AcademicClass.objects.select_related("academic_level"),
        pk=class_id,
    )
    allocations = _teacher_class_allocations(employee, academic_class)
    if not allocations:
        return None, academic_class, None
    if subject_id is None:
        return allocations, academic_class, None
    allocation = next((item for item in allocations if item.learning_area_id == subject_id), None)
    return allocations, academic_class, allocation


def _teacher_elearning_allocated_levels(employee):
    allocations = (
        ELearningSubjectAllocation.objects.filter(teacher=employee)
        .select_related("academic_level", "learning_area")
        .order_by(
            "academic_level__order",
            "academic_level__name",
            "learning_area__display_order",
            "learning_area__name",
        )
    )
    grouped = OrderedDict()
    for allocation in allocations:
        level = allocation.academic_level
        if level.status != AcademicLevel.Status.ACTIVE:
            continue
        group = grouped.setdefault(
            level.id,
            {"level": level, "allocations": [], "subjects": OrderedDict()},
        )
        group["allocations"].append(allocation)
        group["subjects"][allocation.learning_area_id] = allocation.learning_area
    return [
        {
            "level": item["level"],
            "allocations": item["allocations"],
            "subjects": list(item["subjects"].values()),
            "subject_count": len(item["subjects"]),
        }
        for item in grouped.values()
    ]


def _teacher_elearning_level_allocations(employee, academic_level):
    return list(
        ELearningSubjectAllocation.objects.filter(
            teacher=employee,
            academic_level=academic_level,
        )
        .select_related("learning_area", "academic_level")
        .order_by("learning_area__display_order", "learning_area__name")
    )


def _teacher_elearning_allocation_or_redirect(employee, level_id, subject_id=None):
    academic_level = get_object_or_404(AcademicLevel, pk=level_id)
    allocations = _teacher_elearning_level_allocations(employee, academic_level)
    if not allocations:
        return None, academic_level, None
    if subject_id is None:
        return allocations, academic_level, None
    allocation = next((item for item in allocations if item.learning_area_id == subject_id), None)
    return allocations, academic_level, allocation


def _require_teacher_elearning_access(request):
    denied = _require_teacher_workspace(request)
    if denied:
        return denied, None
    employee = workspace_view_employee(request)
    if not ELearningSubjectAllocation.objects.filter(teacher=employee).exists():
        error(request, "E-learning unlocks when you are allocated an e-learning subject.")
        return redirect("employees:role_dashboard", role="teacher"), None
    return None, employee


def _teacher_learning_session_allocations(employee):
    return list(
        ClassSubjectAllocation.objects.filter(teacher=employee)
        .select_related(
            "academic_class",
            "academic_class__academic_level",
            "learning_area",
        )
        .filter(
            academic_class__status=AcademicClass.Status.ACTIVE,
            academic_class__academic_level__status=AcademicLevel.Status.ACTIVE,
        )
        .order_by(
            "academic_class__academic_level__order",
            "academic_class__academic_level__name",
            "academic_class__order",
            "academic_class__name",
            "learning_area__display_order",
            "learning_area__name",
        )
    )


def _parse_optional_int(raw):
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _teacher_learning_report_scope(allocations, level_id=None, class_id=None, subject_id=None):
    levels = []
    classes = []
    subjects = []
    seen_levels = set()
    seen_classes = set()
    seen_subjects = set()
    for allocation in allocations:
        level = allocation.academic_class.academic_level
        academic_class = allocation.academic_class
        subject = allocation.learning_area
        if level.id not in seen_levels:
            seen_levels.add(level.id)
            levels.append({"id": level.id, "name": level.name})
        if academic_class.id not in seen_classes:
            seen_classes.add(academic_class.id)
            classes.append(
                {
                    "id": academic_class.id,
                    "name": academic_class.name,
                    "level_id": level.id,
                }
            )
        subject_key = (academic_class.id, subject.id)
        if subject_key not in seen_subjects:
            seen_subjects.add(subject_key)
            subjects.append(
                {
                    "id": subject.id,
                    "name": subject.name,
                    "class_id": academic_class.id,
                    "level_id": level.id,
                }
            )

    scoped = allocations
    if level_id is not None:
        scoped = [
            item
            for item in scoped
            if item.academic_class.academic_level_id == level_id
        ]
    if class_id is not None:
        scoped = [item for item in scoped if item.academic_class_id == class_id]
    if subject_id is not None:
        scoped = [item for item in scoped if item.learning_area_id == subject_id]

    return {
        "levels": levels,
        "classes": classes,
        "subjects": subjects,
        "allocations": scoped,
        "catalog": {
            "levels": levels,
            "classes": classes,
            "subjects": subjects,
        },
    }


def _teacher_elearning_report_scope(allocations, level_id=None, subject_id=None):
    levels = []
    subjects = []
    seen_levels = set()
    seen_subjects = set()
    for allocation in allocations:
        level = allocation.academic_level
        subject = allocation.learning_area
        if level.id not in seen_levels:
            seen_levels.add(level.id)
            levels.append({"id": level.id, "name": level.name})
        subject_key = (level.id, subject.id)
        if subject_key not in seen_subjects:
            seen_subjects.add(subject_key)
            subjects.append(
                {
                    "id": subject.id,
                    "name": subject.name,
                    "level_id": level.id,
                }
            )

    scoped = allocations
    if level_id is not None:
        scoped = [item for item in scoped if item.academic_level_id == level_id]
    if subject_id is not None:
        scoped = [item for item in scoped if item.learning_area_id == subject_id]

    return {
        "levels": levels,
        "subjects": subjects,
        "allocations": scoped,
        "catalog": {
            "levels": levels,
            "subjects": subjects,
        },
    }


@login_required
@require_http_methods(["GET"])
def teacher_learning_reports(request):
    denied = _require_teacher_workspace(request)
    if denied:
        return denied
    employee = workspace_view_employee(request)
    allocations = _teacher_learning_session_allocations(employee)

    report_types = (
        ("attendance", "Attendance"),
        ("lesson_plan", "Lesson plan"),
        ("outcome", "Outcome"),
    )
    report_type = (request.GET.get("report_type") or "").strip()
    date_raw = (request.GET.get("report_date") or "").strip()
    generate = (request.GET.get("generate") or "").strip() == "1"
    level_id = _parse_optional_int(request.GET.get("level_id"))
    class_id = _parse_optional_int(request.GET.get("class_id"))
    subject_id = _parse_optional_int(request.GET.get("subject_id"))
    report_date = None
    report_error = ""
    if date_raw:
        try:
            report_date = date.fromisoformat(date_raw)
        except ValueError:
            report_error = "Choose a valid report date."
    elif not generate:
        report_date = date.today()

    scope = _teacher_learning_report_scope(
        allocations,
        level_id=level_id,
        class_id=class_id,
        subject_id=subject_id,
    )
    valid_level_ids = {item["id"] for item in scope["levels"]}
    valid_class_ids = {
        item["id"]
        for item in scope["classes"]
        if level_id is None or item["level_id"] == level_id
    }
    valid_subject_ids = {
        item["id"]
        for item in scope["subjects"]
        if (level_id is None or item["level_id"] == level_id)
        and (class_id is None or item["class_id"] == class_id)
    }
    if level_id is not None and level_id not in valid_level_ids:
        level_id = None
    if class_id is not None and class_id not in valid_class_ids:
        class_id = None
    if subject_id is not None and subject_id not in valid_subject_ids:
        subject_id = None
    scope = _teacher_learning_report_scope(
        allocations,
        level_id=level_id,
        class_id=class_id,
        subject_id=subject_id,
    )
    scoped_allocations = scope["allocations"]
    allocation_ids = [item.id for item in scoped_allocations]

    selection = {
        "report_date": report_date.isoformat() if report_date else date_raw,
        "report_type": report_type if report_type in {item[0] for item in report_types} else "attendance",
        "level_id": level_id or "",
        "class_id": class_id or "",
        "subject_id": subject_id or "",
    }
    context = {
        "active_nav": "learning-reports",
        "teacher_employee": employee,
        "school_profile": SchoolProfile.objects.filter(pk=1).first(),
        "allocations": allocations,
        "allocation_count": len(scoped_allocations) if generate else len(allocations),
        "report_types": report_types,
        "selection": selection,
        "report_error": report_error,
        "has_report": False,
        "scope_levels": scope["levels"],
        "scope_classes": scope["classes"],
        "scope_subjects": scope["subjects"],
        "scope_catalog": scope["catalog"],
    }

    if not allocations:
        return render(request, "employees/teacher_learning_report.html", context)

    if not generate:
        return render(request, "employees/teacher_learning_report.html", context)

    if report_error:
        return render(request, "employees/teacher_learning_report.html", context)
    if not report_date:
        context["report_error"] = "Select a date for the report."
        return render(request, "employees/teacher_learning_report.html", context)
    if selection["report_type"] not in {item[0] for item in report_types}:
        context["report_error"] = "Choose attendance, lesson plan, or outcome."
        return render(request, "employees/teacher_learning_report.html", context)
    if not level_id:
        context["report_error"] = "Select an academic level."
        return render(request, "employees/teacher_learning_report.html", context)
    if not class_id:
        context["report_error"] = "Select a class."
        return render(request, "employees/teacher_learning_report.html", context)
    if not subject_id:
        context["report_error"] = "Select a subject."
        return render(request, "employees/teacher_learning_report.html", context)
    if not scoped_allocations:
        context["report_error"] = "That level, class, and subject are not allocated to you."
        return render(request, "employees/teacher_learning_report.html", context)

    report_type_label = dict(report_types)[selection["report_type"]]
    attendance_rows = []
    lesson_plan_rows = []
    outcome_rows = []
    session_total = 0
    plan_count = 0
    outcome_count = 0
    selected_scope_label = (
        f"{scoped_allocations[0].academic_class.name} · "
        f"{scoped_allocations[0].learning_area.name}"
    )

    if selection["report_type"] == "attendance":
        sessions = list(
            SubjectAttendanceSession.objects.filter(
                allocation_id__in=allocation_ids,
                lesson_date=report_date,
            )
            .select_related(
                "allocation__academic_class",
                "allocation__academic_class__academic_level",
                "allocation__learning_area",
                "taken_by",
            )
            .prefetch_related(
                Prefetch(
                    "records",
                    queryset=SubjectAttendanceRecord.objects.select_related(
                        "student"
                    ).order_by("student__last_name", "student__first_name"),
                )
            )
            .order_by(
                "allocation__academic_class__academic_level__order",
                "allocation__academic_class__order",
                "allocation__learning_area__name",
            )
        )
        for session in sessions:
            counts = {
                SubjectAttendanceRecord.Status.PRESENT: 0,
                SubjectAttendanceRecord.Status.ABSENT: 0,
                SubjectAttendanceRecord.Status.LATE: 0,
                SubjectAttendanceRecord.Status.EXCUSED: 0,
            }
            learners = []
            for record in session.records.all():
                if record.status in counts:
                    counts[record.status] += 1
                learners.append(
                    {
                        "student": record.student,
                        "status": record.status,
                        "status_label": record.get_status_display(),
                    }
                )
            recorded = sum(counts.values())
            present = counts[SubjectAttendanceRecord.Status.PRESENT]
            attendance_rows.append(
                {
                    "session": session,
                    "allocation": session.allocation,
                    "present": present,
                    "absent": counts[SubjectAttendanceRecord.Status.ABSENT],
                    "late": counts[SubjectAttendanceRecord.Status.LATE],
                    "excused": counts[SubjectAttendanceRecord.Status.EXCUSED],
                    "recorded": recorded,
                    "rate": round((present / recorded) * 100) if recorded else None,
                    "learners": learners,
                }
            )
        session_total = len(attendance_rows)

    elif selection["report_type"] == "lesson_plan":
        plans = {
            plan.allocation_id: plan
            for plan in ClassSubjectLessonPlan.objects.filter(
                allocation_id__in=allocation_ids
            ).select_related("updated_by")
        }
        for allocation in scoped_allocations:
            plan = plans.get(allocation.id)
            has_plan = plan is not None
            if has_plan:
                plan_count += 1
            lesson_plan_rows.append(
                {
                    "allocation": allocation,
                    "plan": plan,
                    "has_plan": has_plan,
                    "strand": (plan.strand if plan else "") or "",
                    "substrand": (plan.substrand if plan else "") or "",
                    "outcomes": (plan.lesson_learning_outcomes if plan else "") or "",
                    "key_inquiry_questions": (plan.key_inquiry_questions if plan else "") or "",
                    "core_competencies": (plan.core_competencies if plan else "") or "",
                    "values": (plan.values if plan else "") or "",
                    "learning_resources": (plan.learning_resources if plan else "") or "",
                    "introduction": (plan.introduction if plan else "") or "",
                    "lesson_development": (plan.lesson_development if plan else "") or "",
                    "updated_at": plan.updated_at if plan else None,
                }
            )

    else:
        outcomes = {
            item.allocation_id: item
            for item in ClassSubjectOutcome.objects.filter(
                allocation_id__in=allocation_ids
            ).select_related("updated_by")
        }
        for allocation in scoped_allocations:
            outcome = outcomes.get(allocation.id)
            outcome_text = (outcome.outcome if outcome else "") or ""
            has_outcome = bool(outcome_text.strip())
            if has_outcome:
                outcome_count += 1
            outcome_rows.append(
                {
                    "allocation": allocation,
                    "outcome": outcome,
                    "has_outcome": has_outcome,
                    "outcome_text": outcome_text,
                    "updated_at": outcome.updated_at if outcome else None,
                }
            )

    context.update(
        {
            "has_report": True,
            "report_date": report_date,
            "report_type": selection["report_type"],
            "report_type_label": report_type_label,
            "selected_scope_label": selected_scope_label,
            "generated_at": datetime.now(),
            "attendance_rows": attendance_rows,
            "lesson_plan_rows": lesson_plan_rows,
            "outcome_rows": outcome_rows,
            "session_total": session_total,
            "plan_count": plan_count,
            "outcome_count": outcome_count,
            "allocation_count": len(scoped_allocations),
        }
    )
    return render(request, "employees/teacher_learning_report.html", context)


@login_required
@require_http_methods(["GET"])
def teacher_subject_attendance(request):
    denied = _require_teacher_workspace(request)
    if denied:
        return denied
    employee = workspace_view_employee(request)
    level_groups = _teacher_allocated_levels(employee)
    class_count = sum(len(group["classes"]) for group in level_groups)
    return render(
        request,
        "employees/teacher_subject_attendance.html",
        {
            "active_nav": "subject-attendance",
            "level_groups": level_groups,
            "class_count": class_count,
        },
    )


@login_required
@require_http_methods(["GET"])
def teacher_subject_attendance_class(request, class_id):
    denied = _require_teacher_workspace(request)
    if denied:
        return denied
    employee = workspace_view_employee(request)
    allocations, academic_class, _allocation = _teacher_allocation_or_redirect(employee, class_id)
    is_class_teacher = academic_class.class_teacher_id == employee.id
    if not allocations and not is_class_teacher:
        error(request, "That class is not allocated to you.")
        return redirect("employees:teacher_subject_attendance")
    if is_class_teacher:
        return teacher_class_subject_attendance_overview(request, employee, academic_class)

    allocated_classes = _teacher_allocated_classes(employee)
    allocation_ids = [item.id for item in allocations]
    plan_ids = set(
        ClassSubjectLessonPlan.objects.filter(allocation_id__in=allocation_ids).values_list(
            "allocation_id", flat=True
        )
    )
    outcome_ids = set(
        ClassSubjectOutcome.objects.filter(allocation_id__in=allocation_ids).values_list(
            "allocation_id", flat=True
        )
    )
    attendance_ids = set(
        SubjectAttendanceSession.objects.filter(allocation_id__in=allocation_ids)
        .values_list("allocation_id", flat=True)
        .distinct()
    )
    for item in allocations:
        item.has_lesson_plan = item.id in plan_ids
        item.has_outcome = item.id in outcome_ids
        item.has_attendance = item.id in attendance_ids
        item.is_own_allocation = True
    return render(
        request,
        "employees/teacher_subject_attendance_class.html",
        {
            "active_nav": "subject-attendance",
            "selected_class": academic_class,
            "allocations": allocations,
            "allocated_classes": allocated_classes,
            "is_class_teacher": False,
            "teacher_subject_home_url": reverse("employees:teacher_subject_attendance"),
        },
    )


def _academic_calendar_years():
    return list(
        AcademicYear.objects.filter(status=AcademicYear.Status.ACTIVE)
        .prefetch_related(
            Prefetch("terms", queryset=AcademicTerm.objects.order_by("order", "start_date", "name"))
        )
        .order_by("-is_current", "-start_date", "name")
    )


def _term_period_range(term, period_number):
    """Split a term at midterm into Period 1 and Period 2."""
    if period_number == 1:
        return term.start_date, term.midterm_date
    from datetime import timedelta

    period_start = term.midterm_date + timedelta(days=1)
    if period_start > term.end_date:
        period_start = term.midterm_date
    return period_start, term.end_date


def _resolve_subject_attendance_filter(request):
    """
    Resolve scope (day/period/term/year) and date range from query params.
    Returns a context-ready dict.
    """
    scopes = {"day", "period", "term", "year"}
    scope = (request.GET.get("scope") or "day").strip().lower()
    if scope not in scopes:
        scope = "day"

    date_raw = (request.GET.get("date") or "").strip()
    try:
        attendance_date = date.fromisoformat(date_raw) if date_raw else date.today()
    except ValueError:
        attendance_date = date.today()

    years = _academic_calendar_years()
    year_by_id = {year.id: year for year in years}

    year_id_raw = (request.GET.get("year") or "").strip()
    term_id_raw = (request.GET.get("term") or "").strip()
    period_raw = (request.GET.get("period") or "").strip()

    selected_year = None
    if year_id_raw.isdigit():
        selected_year = year_by_id.get(int(year_id_raw))
    if selected_year is None:
        for year in years:
            if year.start_date <= attendance_date <= year.end_date:
                selected_year = year
                break
    if selected_year is None:
        selected_year = next((year for year in years if year.is_current), None) or (
            years[0] if years else None
        )

    terms = list(selected_year.terms.all()) if selected_year else []
    term_by_id = {term.id: term for term in terms}
    selected_term = None
    if term_id_raw.isdigit():
        selected_term = term_by_id.get(int(term_id_raw))
    if selected_term is None:
        selected_term = next((term for term in terms if term.is_current), None)
    if selected_term is None:
        for term in terms:
            if term.start_date <= attendance_date <= term.end_date:
                selected_term = term
                break
    if selected_term is None and terms:
        selected_term = terms[0]

    try:
        selected_period = int(period_raw) if period_raw else 0
    except ValueError:
        selected_period = 0
    if selected_period not in (1, 2):
        if selected_term and attendance_date <= selected_term.midterm_date:
            selected_period = 1
        else:
            selected_period = 2

    range_start = attendance_date
    range_end = attendance_date
    filter_title = attendance_date.strftime("%A, %d %B %Y")
    filter_subtitle = "One day at a time. Choose a date to see whether each student attended each subject."
    percent_hint = "Cells show attendance percentage for the selected range."

    if scope == "year":
        if selected_year:
            range_start = selected_year.start_date
            range_end = selected_year.end_date
            filter_title = f"Academic year {selected_year.name}"
        else:
            filter_title = "Academic year"
        filter_subtitle = (
            f"{range_start.strftime('%d %b %Y')} – {range_end.strftime('%d %b %Y')}. {percent_hint}"
        )
        attendance_date = min(max(attendance_date, range_start), range_end)
    elif scope == "term":
        if selected_term:
            range_start = selected_term.start_date
            range_end = selected_term.end_date
            filter_title = f"{selected_term.name} · {selected_year.name if selected_year else ''}".strip(
                " ·"
            )
        elif selected_year:
            range_start = selected_year.start_date
            range_end = selected_year.end_date
            filter_title = f"Academic year {selected_year.name}"
        else:
            filter_title = "Term"
        filter_subtitle = (
            f"{range_start.strftime('%d %b %Y')} – {range_end.strftime('%d %b %Y')}. {percent_hint}"
        )
        attendance_date = min(max(attendance_date, range_start), range_end)
    elif scope == "period":
        if selected_term:
            range_start, range_end = _term_period_range(selected_term, selected_period)
            filter_title = (
                f"Period {selected_period} · {selected_term.name}"
                f"{f' · {selected_year.name}' if selected_year else ''}"
            )
        elif selected_year:
            range_start = selected_year.start_date
            range_end = selected_year.end_date
            filter_title = f"Period · Academic year {selected_year.name}"
        else:
            filter_title = f"Period {selected_period}"
        filter_subtitle = (
            f"{range_start.strftime('%d %b %Y')} – {range_end.strftime('%d %b %Y')}. "
            f"Period 1 runs to midterm; Period 2 runs after midterm. {percent_hint}"
        )
        attendance_date = min(max(attendance_date, range_start), range_end)
    else:
        scope = "day"
        range_start = attendance_date
        range_end = attendance_date

    period_options = []
    if selected_term:
        p1_start, p1_end = _term_period_range(selected_term, 1)
        p2_start, p2_end = _term_period_range(selected_term, 2)
        period_options = [
            {
                "value": 1,
                "label": f"Period 1 ({p1_start.strftime('%d %b')} – {p1_end.strftime('%d %b')})",
            },
            {
                "value": 2,
                "label": f"Period 2 ({p2_start.strftime('%d %b')} – {p2_end.strftime('%d %b')})",
            },
        ]

    calendar_options = {}
    for year in years:
        year_terms = []
        for term in year.terms.all():
            p1_start, p1_end = _term_period_range(term, 1)
            p2_start, p2_end = _term_period_range(term, 2)
            year_terms.append(
                {
                    "id": term.id,
                    "name": term.name,
                    "periods": [
                        {
                            "value": 1,
                            "label": f"Period 1 ({p1_start.strftime('%d %b')} – {p1_end.strftime('%d %b')})",
                        },
                        {
                            "value": 2,
                            "label": f"Period 2 ({p2_start.strftime('%d %b')} – {p2_end.strftime('%d %b')})",
                        },
                    ],
                }
            )
        calendar_options[str(year.id)] = year_terms

    return {
        "filter_scope": scope,
        "is_day_scope": scope == "day",
        "show_percentages": scope in {"period", "term", "year"},
        "attendance_date": attendance_date,
        "range_start": range_start,
        "range_end": range_end,
        "filter_title": filter_title,
        "filter_subtitle": filter_subtitle,
        "academic_years": years,
        "selected_year": selected_year,
        "selected_year_id": selected_year.id if selected_year else "",
        "year_terms": terms,
        "selected_term": selected_term,
        "selected_term_id": selected_term.id if selected_term else "",
        "selected_period": selected_period,
        "period_options": period_options,
        "calendar_options_json": calendar_options,
    }


def teacher_class_subject_attendance_overview(request, employee, academic_class):
    filter_ctx = _resolve_subject_attendance_filter(request)
    subjects = list(
        ClassSubjectAllocation.objects.filter(academic_class=academic_class)
        .select_related("learning_area", "teacher")
        .order_by("learning_area__display_order", "learning_area__name")
    )
    students = list(_students_in_academic_level(academic_class.academic_level, academic_class))
    allocation_ids = [item.id for item in subjects]
    status_labels = dict(SubjectAttendanceRecord.Status.choices)

    sessions = list(
        SubjectAttendanceSession.objects.filter(
            allocation_id__in=allocation_ids,
            lesson_date__gte=filter_ctx["range_start"],
            lesson_date__lte=filter_ctx["range_end"],
        ).only("id", "allocation_id", "lesson_date")
    )
    session_by_id = {session.id: session for session in sessions}
    sessions_by_allocation = {}
    for session in sessions:
        sessions_by_allocation.setdefault(session.allocation_id, []).append(session)

    present_counts = {}
    recorded_counts = {}
    day_status_by_pair = {}
    if sessions:
        for record in SubjectAttendanceRecord.objects.filter(
            session_id__in=session_by_id.keys()
        ).only("session_id", "student_id", "status"):
            session = session_by_id.get(record.session_id)
            if session is None:
                continue
            key = (session.allocation_id, record.student_id)
            recorded_counts[key] = recorded_counts.get(key, 0) + 1
            if record.status == SubjectAttendanceRecord.Status.PRESENT:
                present_counts[key] = present_counts.get(key, 0) + 1
            if filter_ctx["is_day_scope"]:
                day_status_by_pair[key] = record.status

    student_rows = []
    for student in students:
        cells = []
        for allocation in subjects:
            key = (allocation.id, student.id)
            recorded = recorded_counts.get(key, 0)
            present = present_counts.get(key, 0)
            session_total = len(sessions_by_allocation.get(allocation.id, []))
            if filter_ctx["show_percentages"]:
                if recorded:
                    pct = round((present / recorded) * 100)
                    display = f"{pct}%"
                    if pct >= 80:
                        rate_class = "rate-high"
                    elif pct >= 50:
                        rate_class = "rate-mid"
                    else:
                        rate_class = "rate-low"
                    title = f"{present} present of {recorded} recorded ({pct}%)"
                elif session_total:
                    display = "—"
                    rate_class = "is-empty"
                    title = f"{session_total} subject session(s) recorded, but not for this student"
                else:
                    display = "—"
                    rate_class = "is-empty"
                    title = "No subject attendance recorded in this range"
                cells.append(
                    {
                        "allocation": allocation,
                        "subject": allocation.learning_area,
                        "status": None,
                        "status_label": display,
                        "has_session": session_total > 0,
                        "is_range": True,
                        "present": present,
                        "recorded": recorded,
                        "session_total": session_total,
                        "percent": round((present / recorded) * 100) if recorded else None,
                        "display": display,
                        "rate_class": rate_class,
                        "title": title,
                    }
                )
            else:
                status = day_status_by_pair.get(key)
                cells.append(
                    {
                        "allocation": allocation,
                        "subject": allocation.learning_area,
                        "status": status,
                        "status_label": status_labels.get(status, "—"),
                        "has_session": allocation.id in sessions_by_allocation,
                        "is_range": False,
                        "present": present,
                        "recorded": recorded,
                        "session_total": session_total,
                        "display": status_labels.get(status, "—") if status else "—",
                        "rate_class": f"status-{(status or 'empty').lower()}",
                    }
                )
        student_rows.append({"student": student, "cells": cells})

    allocated_classes = _teacher_allocated_classes(employee)
    led_classes = _teacher_led_classes(employee)
    if all(item.id != academic_class.id for item in allocated_classes):
        academic_class.level_name = academic_class.academic_level.name
        allocated_classes = [academic_class, *allocated_classes]

    context = {
        "active_nav": "subject-attendance",
        "selected_class": academic_class,
        "subjects": subjects,
        "student_rows": student_rows,
        "students": students,
        "allocated_classes": allocated_classes,
        "led_classes": led_classes,
        "own_allocation_ids": {
            item.id for item in subjects if item.teacher_id == employee.id
        },
        "is_class_teacher": True,
        "active_my_class_tool": "subject-attendance-overview",
        "teacher_subject_home_url": reverse(
            "employees:teacher_my_class_page",
            kwargs={"tool": "students-class-attendance"},
        ),
        **filter_ctx,
    }
    return render(
        request,
        "employees/teacher_class_subject_attendance_overview.html",
        context,
    )


@login_required
@require_http_methods(["GET", "POST"])
def teacher_subject_attendance_profile(request, class_id, subject_id):
    denied = _require_teacher_workspace(request)
    if denied:
        return denied
    employee = workspace_view_employee(request)
    allocations, academic_class, allocation = _teacher_allocation_or_redirect(
        employee, class_id, subject_id
    )
    if allocation is None:
        error(request, "That subject is not allocated to you for this class.")
        return redirect("employees:teacher_subject_attendance")

    profile_url = reverse(
        "employees:teacher_subject_attendance_profile",
        kwargs={"class_id": academic_class.id, "subject_id": allocation.learning_area_id},
    )
    sort_mode = _resolve_student_sort(request)
    students = _sorted_students(
        list(
            _students_in_academic_level(
                academic_class.academic_level,
                academic_class,
                sort=sort_mode,
            )
        ),
        sort_mode,
    )
    lesson_plan = ClassSubjectLessonPlan.objects.filter(allocation=allocation).first()
    subject_outcome = ClassSubjectOutcome.objects.filter(allocation=allocation).first()

    lesson_date_raw = (request.POST.get("lesson_date") if request.method == "POST" else None) or (
        request.GET.get("date") or ""
    ).strip()
    try:
        lesson_date = date.fromisoformat(lesson_date_raw) if lesson_date_raw else date.today()
    except ValueError:
        lesson_date = date.today()

    if request.method == "POST":
        action = (request.POST.get("form_action") or "").strip()
        if action == "lesson_plan":
            ClassSubjectLessonPlan.objects.update_or_create(
                allocation=allocation,
                defaults={
                    "strand": (request.POST.get("strand") or "").strip()[:255],
                    "substrand": (request.POST.get("substrand") or "").strip()[:255],
                    "lesson_learning_outcomes": (
                        request.POST.get("lesson_learning_outcomes") or ""
                    ).strip(),
                    "key_inquiry_questions": (
                        request.POST.get("key_inquiry_questions") or ""
                    ).strip(),
                    "core_competencies": (request.POST.get("core_competencies") or "").strip(),
                    "values": (request.POST.get("values") or "").strip(),
                    "pcis": (request.POST.get("pcis") or "").strip(),
                    "learning_resources": (request.POST.get("learning_resources") or "").strip(),
                    "organization_of_learning": (
                        request.POST.get("organization_of_learning") or ""
                    ).strip(),
                    "introduction": (request.POST.get("introduction") or "").strip(),
                    "lesson_development": (request.POST.get("lesson_development") or "").strip(),
                    "updated_by": employee,
                },
            )
            success(request, "Lesson plan saved.")
            return redirect(_with_student_sort(f"{profile_url}#lesson-plan", sort_mode))
        if action == "outcome":
            ClassSubjectOutcome.objects.update_or_create(
                allocation=allocation,
                defaults={
                    "outcome": (request.POST.get("outcome") or "").strip(),
                    "updated_by": employee,
                },
            )
            success(request, "Class subject outcome saved.")
            return redirect(
                _with_student_sort(
                    f"{profile_url}?date={lesson_date.isoformat()}#outcome",
                    sort_mode,
                )
            )
        if action == "attendance":
            session, _created = SubjectAttendanceSession.objects.update_or_create(
                allocation=allocation,
                lesson_date=lesson_date,
                defaults={
                    "notes": (request.POST.get("attendance_notes") or "").strip(),
                    "taken_by": employee,
                },
            )
            valid_statuses = {choice for choice, _label in SubjectAttendanceRecord.Status.choices}
            student_ids = {student.id for student in students}
            bulk_upsert_by_keys(
                SubjectAttendanceRecord,
                scope_filter={"session_id": session.id},
                create_defaults={"session_id": session.id},
                rows=[
                    {
                        "student_id": student.id,
                        "status": (
                            (request.POST.get(f"status_{student.id}") or "").strip().upper()
                            if (request.POST.get(f"status_{student.id}") or "").strip().upper()
                            in valid_statuses
                            else SubjectAttendanceRecord.Status.PRESENT
                        ),
                    }
                    for student in students
                ],
                key_fields=("student_id",),
                update_fields=("status",),
            )
            SubjectAttendanceRecord.objects.filter(session=session).exclude(
                student_id__in=student_ids
            ).delete()
            success(request, f"Attendance saved for {lesson_date.strftime('%d %b %Y')}.")
            return redirect(
                _with_student_sort(
                    f"{profile_url}?date={lesson_date.isoformat()}#attendance",
                    sort_mode,
                )
            )
        error(request, "Unknown form action.")
        return redirect(_with_student_sort(profile_url, sort_mode))

    attendance_session = SubjectAttendanceSession.objects.filter(
        allocation=allocation, lesson_date=lesson_date
    ).first()
    status_lookup = {}
    if attendance_session:
        status_lookup = {
            record.student_id: record.status
            for record in attendance_session.records.all()
        }
    for student in students:
        student.attendance_status = status_lookup.get(
            student.id, SubjectAttendanceRecord.Status.PRESENT
        )

    return render(
        request,
        "employees/teacher_subject_attendance_profile.html",
        {
            "active_nav": "subject-attendance",
            "selected_class": academic_class,
            "allocation": allocation,
            "subject": allocation.learning_area,
            "allocations": allocations,
            "allocated_classes": _teacher_allocated_classes(employee),
            "teacher_subject_home_url": reverse("employees:teacher_subject_attendance"),
            "students": students,
            "lesson_plan": lesson_plan,
            "subject_outcome": subject_outcome,
            "lesson_date": lesson_date,
            "attendance_session": attendance_session,
            "attendance_statuses": SubjectAttendanceRecord.Status.choices,
            **_student_sort_template_context(request, anchor="attendance"),
        },
    )


@login_required
@require_http_methods(["GET"])
def workspace_role_employees(request):
    if not can_switch_workspace_role(request.user):
        return JsonResponse({"employees": []}, status=403)
    role = (request.GET.get("role") or "").upper()
    if role not in {value for value, _label in Employee.Role.choices}:
        return JsonResponse({"employees": []}, status=400)
    employees = employees_for_workspace_role(role)
    return JsonResponse(
        {
            "role": role,
            "employees": [
                {
                    "id": employee.pk,
                    "name": employee.display_name,
                    "code": employee.employee_code,
                    "email": employee.email,
                    "is_self": employee.pk == request.user.pk,
                }
                for employee in employees
            ],
        }
    )


@login_required
@require_http_methods(["GET"])
def workspace_student_search(request):
    query = (request.GET.get("q") or "").strip()
    if len(query) < 1:
        return JsonResponse({"students": []})

    students = (
        Student.objects.annotate(
            full_name=Concat(
                "first_name",
                Value(" "),
                "last_name",
            )
        )
        .filter(
            Q(full_name__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(admission_number__icontains=query)
            | Q(assessment_number__icontains=query)
        )
        .order_by("last_name", "first_name")[:12]
    )
    return JsonResponse(
        {
            "students": [
                {
                    "id": student.pk,
                    "name": student.display_name,
                    "admission_number": student.admission_number or "",
                    "assessment_number": student.assessment_number,
                    "class_group": student.class_group
                    or student.get_academic_level_display(),
                    "academic_level": student.academic_level,
                    "level_label": student.get_academic_level_display(),
                    "profile_url": reverse(
                        "employees:workspace_student_profile",
                        kwargs={"student_id": student.pk},
                    ),
                }
                for student in students
            ],
        }
    )


@login_required
@require_POST
def switch_workspace_role(request):
    if not can_switch_workspace_role(request.user):
        return redirect_to_role_dashboard(request)
    role = (request.POST.get("role") or "").upper()
    if role not in {value for value, _label in Employee.Role.choices}:
        return redirect_to_role_dashboard(request)
    employee_id = (request.POST.get("employee_id") or "").strip()
    own_roles = user_role_values(request.user)
    if role in own_roles and not employee_id:
        clear_workspace_preview(request)
        set_active_workspace_role(request, role)
        return redirect("employees:role_dashboard", role=role.lower())
    if not employee_id.isdigit():
        return redirect_to_role_dashboard(request)
    employee = employees_for_workspace_role(role).filter(pk=int(employee_id)).first()
    if employee is None:
        return redirect_to_role_dashboard(request)
    if employee.pk == request.user.pk and role in own_roles:
        clear_workspace_preview(request)
        set_active_workspace_role(request, role)
    else:
        request.session[WORKSPACE_ROLE_SESSION_KEY] = role
        request.session[WORKSPACE_VIEW_EMPLOYEE_SESSION_KEY] = employee.pk
    return redirect("employees:role_dashboard", role=role.lower())


@login_required
def it_support_module(request, module):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = _it_support_module(module)
    if current is None:
        return redirect_to_role_dashboard(request)
    if current["slug"] == "curriculum-management":
        template = "employees/it_support_curriculum.html"
    elif current["slug"] == "student-management":
        template = "employees/it_support_student_management.html"
    elif current["slug"] == "reports":
        template = "employees/it_support_reports.html"
    else:
        template = "employees/it_support_module.html"
    students = []
    student_context = {}
    if current["slug"] == "student-management":
        student_context = _student_management_context(request)
    return render(
        request,
        template,
        {
            "active_nav": "dashboard",
            "active_module": current["slug"],
            "module": current,
            "curriculum_sections": IT_SUPPORT_CURRICULUM_SECTIONS,
            "report_sections": IT_SUPPORT_REPORT_SECTIONS,
            **student_context,
        },
    )


@login_required
def it_support_report_section(request, section):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = _it_support_report_section(section)
    if current is None:
        return redirect("employees:it_support_module", module="reports")
    if current["slug"] == "curriculum-reports":
        template = "employees/it_support_curriculum_reports.html"
        extra_context = {
            "curriculum_report_pages": IT_SUPPORT_CURRICULUM_REPORT_PAGES,
            **_curriculum_report_urls(Employee.Role.IT_SUPPORT),
        }
    else:
        template = "employees/it_support_report_section.html"
        extra_context = {}
    return render(
        request,
        template,
        {
            "active_nav": "dashboard",
            "active_report": current["slug"],
            "section": current,
            "report_sections": IT_SUPPORT_REPORT_SECTIONS,
            **extra_context,
        },
    )


def _render_curriculum_report_page(request, page, role):
    current = _it_support_curriculum_report_page(page)
    if current is None:
        return _curriculum_reports_redirect(role)
    if current["slug"] == "exam-reports":
        return _render_exam_reports(request, current, role)
    return render(
        request,
        "employees/it_support_curriculum_report_page.html",
        {
            "active_nav": "dashboard",
            "active_report": "curriculum-reports",
            "active_curriculum_report": current["slug"],
            "page": current,
            "curriculum_report_pages": IT_SUPPORT_CURRICULUM_REPORT_PAGES,
            **_curriculum_report_urls(role),
        },
    )


@login_required
def it_support_curriculum_report_page(request, page):
    denied, role = _require_curriculum_reports(request)
    if denied:
        return denied
    if role != Employee.Role.IT_SUPPORT:
        return redirect_to_role_dashboard(request)
    return _render_curriculum_report_page(request, page, role)


def _exam_report_builder_catalog():
    active_classes = AcademicClass.objects.filter(status=AcademicClass.Status.ACTIVE).order_by(
        "order", "name"
    )
    generations = list(
        GeneratedExamTimetable.objects.select_related("academic_year", "academic_term")
        .prefetch_related(
            Prefetch(
                "academic_levels",
                queryset=AcademicLevel.objects.order_by("order", "name").prefetch_related(
                    Prefetch("classes", queryset=active_classes)
                ),
            )
        )
        .order_by("-academic_year__start_date", "academic_term__order", "-created_at")
    )
    years_by_key = OrderedDict()
    for exam in generations:
        levels = []
        for level in exam.academic_levels.all():
            levels.append(
                {
                    "id": level.id,
                    "name": level.name,
                    "classes": [
                        {
                            "id": academic_class.id,
                            "name": academic_class.name,
                            "label": academic_class.display_label,
                        }
                        for academic_class in level.classes.all()
                    ],
                }
            )
        if not levels:
            continue
        year = exam.academic_year
        year_key = str(year.id) if year is not None else "none"
        if year_key not in years_by_key:
            years_by_key[year_key] = {
                "id": year_key,
                "name": year.name if year is not None else "Unscheduled",
                "exams": [],
            }
        term_label = exam.academic_term.name if exam.academic_term_id else ""
        year_label = year.name if year is not None else ""
        years_by_key[year_key]["exams"].append(
            {
                "id": exam.id,
                "name": exam.display_name,
                "year_id": year_key,
                "term": term_label,
                "label": " · ".join(
                    part for part in (exam.display_name, year_label, term_label) if part
                ),
                "levels": levels,
            }
        )
    years = list(years_by_key.values())
    for year in years:
        merged_levels = _merge_exam_catalog_levels(year["exams"])
        year["exams"] = [
            {
                "id": "all",
                "name": "All assessments",
                "label": "All assessments",
                "year_id": year["id"],
                "term": "",
                "levels": merged_levels,
            },
            *year["exams"],
        ]
    exams = [exam for year in years for exam in year["exams"] if exam["id"] != "all"]
    return {"years": years, "exams": exams}


def _merge_exam_catalog_levels(exams):
    levels_by_id = OrderedDict()
    for exam in exams:
        for level in exam.get("levels") or []:
            existing = levels_by_id.get(level["id"])
            if existing is None:
                levels_by_id[level["id"]] = {
                    "id": level["id"],
                    "name": level["name"],
                    "classes": list(level.get("classes") or []),
                }
                continue
            known = {item["id"] for item in existing["classes"]}
            for academic_class in level.get("classes") or []:
                if academic_class["id"] not in known:
                    existing["classes"].append(academic_class)
                    known.add(academic_class["id"])
    return list(levels_by_id.values())


def _exam_report_selection(request):
    year_id = (request.GET.get("year_id") or "").strip()
    exam_id = (request.GET.get("exam_id") or "").strip()
    report_kind = (request.GET.get("report_kind") or "").strip()
    level_id = (request.GET.get("level_id") or "").strip()
    level_scope = (request.GET.get("level_scope") or "").strip()
    class_id = (request.GET.get("class_id") or "").strip()
    student_id = (request.GET.get("student_id") or "").strip()
    generate = (request.GET.get("generate") or "").strip() == "1"

    selection = {
        "year_id": year_id,
        "exam_id": exam_id,
        "report_kind": report_kind,
        "level_id": level_id,
        "level_scope": level_scope,
        "class_id": class_id,
        "student_id": student_id,
        "generate": generate,
    }
    if not generate:
        return selection, None

    if not year_id:
        return selection, {"error": "Select an academic year to generate the report."}
    if exam_id != "all" and not exam_id.isdigit():
        return selection, {"error": "Select an assessment to generate the report."}

    if year_id == "none":
        year_filter = {"academic_year__isnull": True}
        academic_year = None
    elif year_id.isdigit():
        academic_year = AcademicYear.objects.filter(pk=int(year_id)).first()
        if academic_year is None:
            return selection, {"error": "The selected academic year could not be found."}
        year_filter = {"academic_year_id": academic_year.id}
    else:
        return selection, {"error": "Select an academic year to generate the report."}

    if exam_id == "all":
        exams = list(
            GeneratedExamTimetable.objects.select_related("academic_year", "academic_term")
            .prefetch_related("academic_levels")
            .filter(**year_filter)
            .order_by("academic_term__order", "created_at")
        )
        if not exams:
            return selection, {"error": "No assessments are registered for the selected academic year."}
        exam = exams[0]
        exam_title = f"All assessments · {academic_year.name if academic_year else 'Unscheduled'}"
    else:
        exam = (
            GeneratedExamTimetable.objects.select_related("academic_year", "academic_term")
            .prefetch_related("academic_levels")
            .filter(pk=int(exam_id), **year_filter)
            .first()
        )
        if exam is None:
            return selection, {"error": "The selected assessment could not be found for that academic year."}
        exams = [exam]
        exam_title = _exam_record_title(exam)

    if report_kind not in {"academic_level", "individual"}:
        return selection, {"error": "Choose whether this is an academic level or individual report."}
    if not level_id.isdigit():
        return selection, {"error": "Select an academic level."}
    level = (
        AcademicLevel.objects.prefetch_related(
            "learning_areas",
            "exam_subject_settings",
            "exam_subject_settings__learning_area",
        )
        .filter(pk=int(level_id))
        .first()
    )
    if level is None:
        return selection, {"error": "The selected academic level could not be found."}
    leveled_exams = [item for item in exams if _exam_has_academic_levels(item)]
    if leveled_exams and not any(
        _exam_includes_academic_level(item, level.id) for item in leveled_exams
    ):
        return selection, {"error": "The selected academic level is not part of the chosen assessment(s)."}

    selected_class = None
    selected_student = None
    students = []

    if report_kind == "academic_level":
        if level_scope not in {"all_level", "individual_class"}:
            return selection, {
                "error": "Choose whether to generate for the whole grade or one class."
            }
        if level_scope == "individual_class":
            if not class_id.isdigit():
                return selection, {"error": "Select a class for the academic level report."}
            selected_class = AcademicClass.objects.select_related("class_teacher").filter(
                pk=int(class_id),
                academic_level=level,
                status=AcademicClass.Status.ACTIVE,
            ).first()
            if selected_class is None:
                return selection, {"error": "The selected class could not be found."}
            students = list(_students_in_academic_level(level, selected_class))
            scope_label = f"{level.name} · {selected_class.display_label}"
        else:
            students = list(_students_in_academic_level(level))
            scope_label = f"{level.name} · whole grade"
        kind_label = "Academic level report"
    else:
        if not class_id.isdigit():
            return selection, {"error": "Select a class for the individual report."}
        selected_class = AcademicClass.objects.select_related("class_teacher").filter(
            pk=int(class_id),
            academic_level=level,
            status=AcademicClass.Status.ACTIVE,
        ).first()
        if selected_class is None:
            return selection, {"error": "The selected class could not be found."}
        if student_id == "all":
            students = list(_students_in_academic_level(level, selected_class))
            if not students:
                return selection, {
                    "error": "No enrolled students matched the selected class.",
                }
            selected_student = None
            scope_label = f"{level.name} · {selected_class.display_label} · all students"
        elif student_id.isdigit():
            selected_student = _students_in_academic_level(level, selected_class).filter(
                pk=int(student_id)
            ).first()
            if selected_student is None:
                return selection, {
                    "error": "The selected student could not be found in that class.",
                }
            students = [selected_student]
            scope_label = (
                f"{level.name} · {selected_class.display_label} · {selected_student.display_name}"
            )
        else:
            return selection, {"error": "Select a student for the individual report."}
        kind_label = "Individual report"

    grade_bands = list(_grade_bands_for_level(level))
    if not grade_bands:
        grade_bands = list(_grade_bands_for_level(None))

    usable_exams = []
    for exam_item in exams:
        if (
            _exam_has_academic_levels(exam_item)
            and not _exam_includes_academic_level(exam_item, level.id)
        ):
            continue
        usable_exams.append(exam_item)
    if not usable_exams:
        return selection, {"error": "No assessment results were found for the selected scope."}

    subjects = _exam_record_subjects(level, selected_class)
    school_profile = SchoolProfile.objects.filter(pk=1).first()
    class_teacher_name = ""
    if selected_class is not None and selected_class.class_teacher_id:
        class_teacher_name = selected_class.class_teacher.display_name
    head_of_institution = (
        Employee.objects.filter(
            role=Employee.Role.HEAD_OF_INSTITUTION,
            approval_status=Employee.ApprovalStatus.APPROVED,
        )
        .order_by("last_name", "first_name", "employee_code")
        .first()
    )
    head_of_institution_name = (
        head_of_institution.display_name
        if head_of_institution is not None
        else (
            (school_profile.principal_name or "").strip()
            if school_profile is not None
            else ""
        )
    )

    report_cards = []
    matrix_sheets = []
    if report_kind == "individual":
        trend_exams = list(
            GeneratedExamTimetable.objects.select_related("academic_year", "academic_term")
            .prefetch_related("academic_levels")
            .filter(**year_filter)
            .order_by("academic_term__order", "created_at")
        )
        trend_exams = [
            item
            for item in trend_exams
            if (
                not _exam_has_academic_levels(item)
                or _exam_includes_academic_level(item, level.id)
            )
        ]
        report_cards = _build_individual_multi_exam_report_cards(
            students,
            usable_exams,
            subjects,
            level,
            selected_class,
            grade_bands,
            trend_exams=trend_exams or usable_exams,
        )
        if not report_cards and students:
            return selection, {"error": "No assessment results were found for the selected scope."}
    else:
        if not students:
            return selection, {
                "error": (
                    "No enrolled students matched the selected class."
                    if selected_class
                    else "No enrolled students matched the selected academic level."
                ),
            }
        matrix_sheets = _build_level_matrix_sheets(
            students,
            usable_exams,
            subjects,
            level,
            grade_bands,
        )

    return selection, {
        "exam": exam,
        "exam_title": exam_title,
        "kind_label": kind_label,
        "scope_label": scope_label,
        "report_kind": report_kind,
        "level": level,
        "selected_class": selected_class,
        "selected_student": selected_student,
        "students": students,
        "subjects": subjects,
        "student_count": len(students),
        "subject_count": len(subjects),
        "report_cards": report_cards,
        "matrix_sheets": matrix_sheets,
        "is_matrix": report_kind == "academic_level",
        "grade_bands": grade_bands,
        "school_profile": school_profile,
        "class_teacher_name": class_teacher_name,
        "head_of_institution_name": head_of_institution_name,
        "is_individual": report_kind == "individual",
        "issued_on": date.today(),
        "academic_year": academic_year if exam_id == "all" else exam.academic_year,
        "academic_term": None if exam_id == "all" else exam.academic_term,
    }


def _grade_band_for_percent(percent, grade_bands):
    if percent is None:
        return None
    try:
        value = int(percent)
    except (TypeError, ValueError):
        return None
    for band in grade_bands:
        if band.start_percent <= value <= band.end_percent:
            return band
    return None


def _build_individual_trend_chart(exam_columns, exam_means, subject_rows=None):
    """Build print-friendly SVG coords for performance per assessment."""
    exam_points = []
    for column, mean in zip(exam_columns or [], exam_means or []):
        percent = mean.get("percent") if isinstance(mean, dict) else mean
        if percent is None:
            continue
        exam_points.append(
            {
                "label": column.get("label") or "Assessment",
                "title": column.get("title") or "",
                "term": column.get("term") or "",
                "percent": percent,
                "grade": (mean.get("grade") if isinstance(mean, dict) else "") or "",
            }
        )
    if not exam_points:
        return None

    width = 560
    height = 176
    pad_l, pad_r, pad_t, pad_b = 34, 18, 26, 38
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def y_for(percent):
        return round(pad_t + plot_h * (1 - (max(0, min(100, percent)) / 100.0)), 1)

    grid = []
    for tick in (0, 25, 50, 75, 100):
        grid.append({"value": tick, "y": y_for(tick)})

    title = "Performance by assessment"
    subtitle = "Assessment mean trend across assessments"

    if len(exam_points) >= 2:
        n = len(exam_points)
        plotted = []
        for index, point in enumerate(exam_points):
            x = round(pad_l + (plot_w * index / (n - 1)), 1)
            y = y_for(point["percent"])
            plotted.append({**point, "x": x, "y": y})
        line = " ".join(f'{p["x"]},{p["y"]}' for p in plotted)
        area = (
            f'{plotted[0]["x"]},{pad_t + plot_h} '
            + line
            + f' {plotted[-1]["x"]},{pad_t + plot_h}'
        )
        return {
            "mode": "line",
            "title": title,
            "subtitle": subtitle,
            "width": width,
            "height": height,
            "plot_left": pad_l,
            "plot_right": width - pad_r,
            "grid": grid,
            "points": plotted,
            "line": line,
            "area": area,
            "baseline_y": pad_t + plot_h,
        }

    # Single assessment: still show a clear per-assessment bar.
    point = exam_points[0]
    bar_w = 56
    x = round(pad_l + (plot_w - bar_w) / 2, 1)
    y = y_for(point["percent"])
    plotted = [
        {
            **point,
            "x": x,
            "y": y,
            "width": bar_w,
            "height": round(pad_t + plot_h - y, 1),
            "label_x": round(x + bar_w / 2, 1),
        }
    ]
    return {
        "mode": "bars",
        "title": title,
        "subtitle": "Assessment mean for the selected assessment",
        "width": width,
        "height": height,
        "plot_left": pad_l,
        "plot_right": width - pad_r,
        "grid": grid,
        "points": plotted,
        "baseline_y": pad_t + plot_h,
    }


def _build_level_matrix_sheets(students, exams, subjects, level, grade_bands):
    """Return academic-level mark sheets: students as rows, subjects as columns."""
    sheets = []
    marks_by_exam = _exam_record_marks_lookup_multi(exams, students, subjects)
    for exam_item in exams:
        out_of_by_subject = _exam_record_out_of(level, subjects)
        mark_lookup = marks_by_exam.get(exam_item.id, {})
        rows = []
        for student in students:
            cells = []
            scored = []
            for subject in subjects:
                current_out_of = out_of_by_subject.get(subject.id, subject.total_marks)
                entry = mark_lookup.get((student.id, subject.id))
                raw = _exam_mark_entry_raw(entry)
                out_of = _exam_mark_entry_out_of(entry, current_out_of)
                percent = _marks_as_percent(raw, out_of)
                band = _grade_band_for_percent(percent, grade_bands)
                if percent is not None:
                    scored.append(percent)
                cells.append(
                    {
                        "raw": raw,
                        "out_of": out_of,
                        "percent": percent,
                        "grade": band.code if band else "",
                        "meaning": band.meaning if band else "",
                    }
                )
            mean = round(sum(scored) / len(scored)) if scored else None
            mean_band = _grade_band_for_percent(mean, grade_bands)
            rows.append(
                {
                    "student": student,
                    "class_label": (student.class_group or "").strip() or "—",
                    "admission": student.admission_number or "—",
                    "cells": cells,
                    "mean_percent": mean,
                    "overall_grade": mean_band.code if mean_band else "",
                    "overall_meaning": mean_band.meaning if mean_band else "",
                }
            )
        rows.sort(
            key=lambda row: (
                row["mean_percent"] is None,
                -(row["mean_percent"] if row["mean_percent"] is not None else 0),
                (row["student"].last_name or "").casefold(),
                (row["student"].first_name or "").casefold(),
                (row["admission"] or "").casefold(),
            )
        )
        sheets.append(
            {
                "exam_title": _exam_record_title(exam_item),
                "academic_year": exam_item.academic_year,
                "academic_term": exam_item.academic_term,
                "subjects": subjects,
                "rows": rows,
                "student_count": len(rows),
                "subject_count": len(subjects),
            }
        )
    return sheets


def _build_individual_multi_exam_report_cards(
    students, exams, subjects, level, selected_class, grade_bands, trend_exams=None
):
    exam_columns = []
    out_of_by_exam = []
    trend_source = list(trend_exams or exams)
    all_exams = list(dict.fromkeys([*exams, *trend_source]))
    marks_lookup_multi = _exam_record_marks_lookup_multi(all_exams, students, subjects)
    marks_by_exam = [marks_lookup_multi.get(exam_item.id, {}) for exam_item in exams]
    for index, exam_item in enumerate(exams, start=1):
        term_label = (exam_item.academic_term.name if exam_item.academic_term_id else "").strip()
        title = _exam_record_title(exam_item)
        exam_columns.append(
            {
                "id": exam_item.id,
                "title": title,
                "term": term_label,
                "label": f"Assessment {index}",
            }
        )
        out_of_by_subject = _exam_record_out_of(level, subjects)
        out_of_by_exam.append(out_of_by_subject)

    trend_columns = []
    trend_marks = []
    trend_out_of = []
    for index, exam_item in enumerate(trend_source, start=1):
        term_label = (exam_item.academic_term.name if exam_item.academic_term_id else "").strip()
        trend_columns.append(
            {
                "id": exam_item.id,
                "title": _exam_record_title(exam_item),
                "term": term_label,
                "label": f"Assessment {index}",
            }
        )
        trend_out_of.append(_exam_record_out_of(level, subjects))
        trend_marks.append(marks_lookup_multi.get(exam_item.id, {}))

    cards = []
    for student in students:
        rows = []
        subject_means = []
        exam_score_totals = [[] for _ in exams]
        for subject in subjects:
            cells = []
            scored = []
            for exam_index, exam_item in enumerate(exams):
                current_out_of = out_of_by_exam[exam_index].get(subject.id, subject.total_marks)
                entry = marks_by_exam[exam_index].get((student.id, subject.id))
                raw = _exam_mark_entry_raw(entry)
                out_of = _exam_mark_entry_out_of(entry, current_out_of)
                percent = _marks_as_percent(raw, out_of)
                band = _grade_band_for_percent(percent, grade_bands)
                if percent is not None:
                    scored.append(percent)
                    exam_score_totals[exam_index].append(percent)
                cells.append(
                    {
                        "raw": raw,
                        "out_of": out_of,
                        "percent": percent,
                        "grade": band.code if band else "",
                        "points": band.points if band else None,
                        "meaning": band.meaning if band else "",
                    }
                )
            mean = round(sum(scored) / len(scored)) if scored else None
            if mean is not None:
                subject_means.append(mean)
            mean_band = _grade_band_for_percent(mean, grade_bands)
            rows.append(
                {
                    "subject": subject,
                    "cells": cells,
                    "mean_percent": mean,
                    "grade": mean_band.code if mean_band else "",
                    "points": mean_band.points if mean_band else None,
                    "meaning": mean_band.meaning if mean_band else "",
                    "mark_level": mean_band.mark_level if mean_band else "",
                }
            )

        exam_means = []
        for scores in exam_score_totals:
            mean_value = round(sum(scores) / len(scores)) if scores else None
            mean_band = _grade_band_for_percent(mean_value, grade_bands)
            exam_means.append(
                {
                    "percent": mean_value,
                    "grade": mean_band.code if mean_band else "",
                }
            )

        trend_means = []
        for exam_index, _exam_item in enumerate(trend_source):
            scores = []
            for subject in subjects:
                current_out_of = trend_out_of[exam_index].get(subject.id, subject.total_marks)
                entry = trend_marks[exam_index].get((student.id, subject.id))
                raw = _exam_mark_entry_raw(entry)
                out_of = _exam_mark_entry_out_of(entry, current_out_of)
                percent = _marks_as_percent(raw, out_of)
                if percent is not None:
                    scores.append(percent)
            mean_value = round(sum(scores) / len(scores)) if scores else None
            mean_band = _grade_band_for_percent(mean_value, grade_bands)
            trend_means.append(
                {
                    "percent": mean_value,
                    "grade": mean_band.code if mean_band else "",
                }
            )
        trend = _build_individual_trend_chart(trend_columns, trend_means, rows)

        overall_mean = (
            round(sum(subject_means) / len(subject_means)) if subject_means else None
        )
        overall_band = _grade_band_for_percent(overall_mean, grade_bands)
        cards.append(
            {
                "student": student,
                "is_multi_exam": True,
                "exam_columns": exam_columns,
                "exam_means": exam_means,
                "rows": rows,
                "trend": trend,
                "subjects_sat": len(subject_means),
                "mean_percent": overall_mean,
                "total_points": None,
                "overall_grade": overall_band.code if overall_band else "",
                "overall_mark_level": overall_band.mark_level if overall_band else "",
                "overall_meaning": overall_band.meaning if overall_band else "",
                "exam_title": (
                    exam_columns[0]["title"]
                    if len(exam_columns) == 1
                    else f"{len(exam_columns)} assessments"
                ),
                "academic_year": exams[0].academic_year if exams else None,
                "academic_term": exams[0].academic_term if len(exams) == 1 else None,
            }
        )
    return cards


def _build_exam_report_cards(students, grade_bands):
    cards = []
    for student in students:
        rows = []
        scored = []
        points_total = 0
        points_count = 0
        for cell in student.mark_cells:
            percent = cell.get("percent")
            band = _grade_band_for_percent(percent, grade_bands)
            if percent is not None:
                scored.append(percent)
            if band is not None:
                points_total += band.points
                points_count += 1
            rows.append(
                {
                    "subject": cell["subject"],
                    "raw": cell.get("raw"),
                    "out_of": cell.get("out_of"),
                    "percent": percent,
                    "grade": band.code if band else "",
                    "mark_level": band.mark_level if band else "",
                    "meaning": band.meaning if band else "",
                    "points": band.points if band else None,
                }
            )
        mean = round(sum(scored) / len(scored)) if scored else None
        overall_band = _grade_band_for_percent(mean, grade_bands)
        cards.append(
            {
                "student": student,
                "rows": rows,
                "subjects_sat": len(scored),
                "mean_percent": mean,
                "total_points": points_total if points_count else None,
                "overall_grade": overall_band.code if overall_band else "",
                "overall_mark_level": overall_band.mark_level if overall_band else "",
                "overall_meaning": overall_band.meaning if overall_band else "",
            }
        )
    return cards


def _render_exam_reports(request, page, role):
    catalog = _cached_exam_report_builder_catalog()
    selection, report = _exam_report_selection(request)
    return render(
        request,
        "employees/it_support_exam_reports.html",
        {
            "active_nav": "dashboard",
            "active_report": "curriculum-reports",
            "active_curriculum_report": page["slug"],
            "page": page,
            "curriculum_report_pages": IT_SUPPORT_CURRICULUM_REPORT_PAGES,
            "exam_years": catalog["years"],
            "exam_catalog": catalog["exams"],
            "exam_catalog_json": catalog,
            "selection": selection,
            "report": report,
            "report_error": (report or {}).get("error") if report else "",
            **_curriculum_report_urls(role),
        },
    )


@login_required
def it_support_exam_reports(request, page):
    denied, role = _require_curriculum_reports(request)
    if denied:
        return denied
    if role != Employee.Role.IT_SUPPORT:
        return redirect_to_role_dashboard(request)
    return _render_exam_reports(request, page, role)


def _exam_report_export_response(request, role):
    urls = _curriculum_report_urls(role)
    exam_reports_url = reverse(
        urls["curriculum_report_page_url"],
        kwargs={"page": "exam-reports"},
    )
    if (request.GET.get("generate") or "").strip() != "1":
        return redirect(exam_reports_url)
    selection, report = _exam_report_selection(request)
    if not report or report.get("error"):
        query = request.GET.copy()
        query["generate"] = "1"
        return redirect(f"{exam_reports_url}?{query.urlencode()}")
    export_mode = (request.GET.get("export_mode") or "raw").strip()
    if export_mode not in {"raw", "graded"}:
        export_mode = "raw"
    workbook_bytes, filename = build_exam_report_excel(report, mode=export_mode)
    response = HttpResponse(
        workbook_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _exam_report_students_response(request):
    level_id = (request.GET.get("level_id") or "").strip()
    class_id = (request.GET.get("class_id") or "").strip()
    if not level_id.isdigit() or not class_id.isdigit():
        return JsonResponse({"students": []})
    level = AcademicLevel.objects.filter(pk=int(level_id)).first()
    academic_class = AcademicClass.objects.filter(
        pk=int(class_id),
        academic_level_id=int(level_id),
        status=AcademicClass.Status.ACTIVE,
    ).first()
    if level is None or academic_class is None:
        return JsonResponse({"students": []})
    students = [
        {
            "id": student.id,
            "name": student.display_name,
            "admission": student.admission_number or "",
        }
        for student in _students_in_academic_level(level, academic_class)
    ]
    return JsonResponse({"students": students})


@login_required
def it_support_exam_report_export(request):
    denied, role = _require_curriculum_reports(request)
    if denied:
        return denied
    if role != Employee.Role.IT_SUPPORT:
        return redirect_to_role_dashboard(request)
    return _exam_report_export_response(request, role)


@login_required
def it_support_exam_report_students(request):
    denied, role = _require_curriculum_reports(request)
    if denied:
        return denied
    if role != Employee.Role.IT_SUPPORT:
        return JsonResponse({"students": []}, status=403)
    return _exam_report_students_response(request)


def _employee_code_sort_key(employee):
    raw = employee.employment_number
    if raw is None or raw == "":
        code = (employee.employee_code or "").strip()
        match = re.match(r"^(\D*?)(\d+)(.*)$", code, flags=re.IGNORECASE)
        if match:
            prefix, digits, suffix = match.groups()
            return (1, prefix.casefold(), int(digits), suffix.casefold())
        if code:
            return (1, code.casefold(), 0, "")
        return (2, "", 0, "")
    try:
        return (0, "", int(raw), "")
    except (TypeError, ValueError):
        text = str(raw).strip()
        match = re.match(r"^(\D*?)(\d+)(.*)$", text, flags=re.IGNORECASE)
        if match:
            prefix, digits, suffix = match.groups()
            return (0, prefix.casefold(), int(digits), suffix.casefold())
        return (0, text.casefold(), 0, "")


@login_required
def it_support_employee_management(request):
    denied = _require_it_support(request)
    if denied:
        return denied
    sort_mode = _resolve_student_sort(request)
    employees = list(Employee.objects.prefetch_related("assigned_roles").all())
    if sort_mode == STUDENT_SORT_ADMISSION:
        employees.sort(
            key=lambda employee: (
                _employee_code_sort_key(employee),
                (employee.first_name or "").casefold(),
                (employee.last_name or "").casefold(),
                (employee.employee_code or "").casefold(),
            )
        )
    else:
        employees.sort(
            key=lambda employee: (
                (employee.first_name or "").casefold(),
                (employee.last_name or "").casefold(),
                _employee_code_sort_key(employee),
            )
        )
    approved_count = sum(
        1
        for employee in employees
        if employee.approval_status == Employee.ApprovalStatus.APPROVED
    )
    pending_count = sum(
        1
        for employee in employees
        if employee.approval_status == Employee.ApprovalStatus.PENDING_APPROVAL
    )
    suspended_count = sum(1 for employee in employees if employee.is_suspended)
    employee_code_assignments = {
        str(employee.employment_number): {
            "id": employee.id,
            "name": employee.display_name,
        }
        for employee in employees
        if employee.employment_number is not None
    }
    return render(
        request,
        "employees/it_support_employee_management.html",
        {
            "active_nav": "dashboard",
            "active_hr_tool": "employee-management",
            "employees": employees,
            "employee_count": len(employees),
            "approved_count": approved_count,
            "pending_count": pending_count,
            "suspended_count": suspended_count,
            "employee_code_assignments": employee_code_assignments,
            "title_choices": Employee.Title.choices,
            "role_choices": Employee.Role.choices,
            "approval_choices": Employee.ApprovalStatus.choices,
            **_student_sort_template_context(request),
        },
    )


@login_required
@require_POST
def update_workspace_employee(request, employee_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    employee = get_object_or_404(Employee, pk=employee_id)
    form = EmployeeProfileForm(request.POST, instance=employee)
    if form.is_valid():
        try:
            employee = form.save()
        except ValidationError as exc:
            if hasattr(exc, "message_dict"):
                messages = []
                for field_errors in exc.message_dict.values():
                    messages.extend(field_errors)
                error(request, " ".join(messages))
            else:
                error(request, " ".join(getattr(exc, "messages", [str(exc)])))
        else:
            if employee.pk == request.user.pk:
                active = request.session.get(ACTIVE_WORKSPACE_ROLE_SESSION_KEY)
                assigned = employee.role_values()
                if active not in assigned:
                    set_active_workspace_role(request, employee.role)
                if is_workspace_preview(request) and workspace_role(request) not in assigned:
                    clear_workspace_preview(request)
                    set_active_workspace_role(request, employee.role)
            conflict = getattr(form, "_employment_number_conflict", None)
            role_summary = ", ".join(employee.role_labels())
            if form.cleaned_data.get("override_employment_number") and conflict:
                success(
                    request,
                    f"{employee.display_name} was updated. "
                    f"Assigned roles: {role_summary}. "
                    f"{conflict.display_name}'s employee code was cleared.",
                )
            else:
                success(
                    request,
                    f"{employee.display_name} was updated. Assigned roles: {role_summary}.",
                )
    else:
        employment_error = form.errors.get("employment_number")
        roles_error = form.errors.get("roles")
        error(
            request,
            employment_error[0]
            if employment_error
            else roles_error[0]
            if roles_error
            else "The employee could not be updated. Check the required fields.",
        )
    return redirect("employees:it_support_employee_management")


@login_required
@require_POST
def toggle_workspace_employee_status(request, employee_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    employee = get_object_or_404(Employee, pk=employee_id)
    if employee.pk == request.user.pk:
        error(request, "You cannot suspend your own account.")
        return redirect("employees:it_support_employee_management")
    employee.is_suspended = not employee.is_suspended
    employee.save(update_fields=["is_suspended"])
    success(
        request,
        f"{employee.display_name} was {'suspended' if employee.is_suspended else 'unsuspended'}.",
    )
    return redirect("employees:it_support_employee_management")


@login_required
@require_POST
def delete_workspace_employee(request, employee_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    employee = get_object_or_404(Employee, pk=employee_id)
    if employee.pk == request.user.pk:
        error(request, "You cannot delete your own account.")
        return redirect("employees:it_support_employee_management")
    name = employee.display_name
    employee.delete()
    success(request, f"{name} was deleted from the system.")
    return redirect("employees:it_support_employee_management")


def _redirect_student_management():
    return redirect("employees:it_support_module", module="student-management")


def _redirect_pending_admissions():
    return redirect("employees:it_support_pending_admissions")


def _redirect_advance_academic_level():
    return redirect("employees:it_support_advance_academic_level")


def _next_academic_level(level):
    return (
        AcademicLevel.objects.filter(
            status=AcademicLevel.Status.ACTIVE,
            order__gt=level.order,
        )
        .order_by("order", "name")
        .first()
    )


def _matching_class_at_level(source_class, target_level):
    if target_level is None:
        return None
    name = (source_class.name or "").strip()
    candidates = AcademicClass.objects.filter(
        academic_level=target_level,
        status=AcademicClass.Status.ACTIVE,
    )
    if name:
        match = candidates.filter(name__iexact=name).order_by("order", "name").first()
        if match:
            return match
    return candidates.filter(order=source_class.order).order_by("name").first() or candidates.order_by(
        "order", "name"
    ).first()


def _advance_class_group_value(target_class, source_class_group=""):
    if target_class is not None:
        return target_class.display_label
    return (source_class_group or "").strip()


@login_required
def it_support_advance_academic_level(request):
    denied = _require_it_support(request)
    if denied:
        return denied

    classes = list(
        AcademicClass.objects.filter(status=AcademicClass.Status.ACTIVE)
        .select_related("academic_level")
        .order_by("academic_level__order", "academic_level__name", "order", "name")
    )
    level_groups = OrderedDict()
    for academic_class in classes:
        level = academic_class.academic_level
        next_level = _next_academic_level(level)
        target_class = _matching_class_at_level(academic_class, next_level)
        students = list(_students_in_academic_level(level, academic_class))
        group = level_groups.setdefault(
            level.id,
            {
                "level": level,
                "next_level": next_level,
                "classes": [],
            },
        )
        group["classes"].append(
            {
                "academic_class": academic_class,
                "student_count": len(students),
                "next_level": next_level,
                "target_class": target_class,
                "can_advance": bool(next_level and _student_level_choice(next_level)),
            }
        )

    return render(
        request,
        "employees/it_support_advance_academic_level.html",
        {
            "active_nav": "dashboard",
            "level_groups": list(level_groups.values()),
            "class_count": len(classes),
            **_student_management_nav_context(active_tool="advance-academic-level"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def it_support_advance_academic_level_class(request, class_id):
    denied = _require_it_support(request)
    if denied:
        return denied

    academic_class = get_object_or_404(
        AcademicClass.objects.select_related("academic_level"),
        pk=class_id,
        status=AcademicClass.Status.ACTIVE,
    )
    level = academic_class.academic_level
    next_level = _next_academic_level(level)
    target_class = _matching_class_at_level(academic_class, next_level)
    next_choice = _student_level_choice(next_level) if next_level else ""
    students = list(_students_in_academic_level(level, academic_class))
    can_advance = bool(next_level and next_choice)

    if request.method == "POST":
        if not can_advance:
            error(
                request,
                f"{academic_class.display_label} has no next academic level to advance into.",
            )
            return redirect(
                "employees:it_support_advance_academic_level_class",
                class_id=academic_class.id,
            )

        selected_ids = {
            int(value)
            for value in request.POST.getlist("student_id")
            if str(value).isdigit()
        }
        selected_students = [student for student in students if student.id in selected_ids]
        if not selected_students:
            error(request, "Select at least one student to advance.")
            return redirect(
                "employees:it_support_advance_academic_level_class",
                class_id=academic_class.id,
            )

        skipped_count = len(students) - len(selected_students)
        target_class_group = _advance_class_group_value(
            target_class,
            selected_students[0].class_group if selected_students else "",
        )

        with transaction.atomic():
            for student in selected_students:
                student.academic_level = next_choice
                student.class_group = target_class_group
                student.save(update_fields=["academic_level", "class_group"])

        target_label = (
            f"{next_level.name}"
            + (f" · {target_class.display_label}" if target_class else "")
        )
        message = (
            f"Advanced {len(selected_students)} student"
            f"{'' if len(selected_students) == 1 else 's'} "
            f"from {level.name} ({academic_class.display_label}) to {target_label}."
        )
        if skipped_count:
            message += f" {skipped_count} student{' was' if skipped_count == 1 else 's were'} left behind."
        success(request, message)
        return _redirect_advance_academic_level()

    return render(
        request,
        "employees/it_support_advance_academic_level_class.html",
        {
            "active_nav": "dashboard",
            "academic_class": academic_class,
            "level": level,
            "next_level": next_level,
            "target_class": target_class,
            "next_choice": next_choice,
            "students": students,
            "student_count": len(students),
            "can_advance": can_advance,
            **_student_management_nav_context(active_tool="advance-academic-level"),
        },
    )


@login_required
def it_support_pending_admissions(request):
    denied = _require_it_support(request)
    if denied:
        return denied
    sort_mode = _resolve_student_sort(request)
    students = list(
        _pending_admission_queryset().order_by(
            "-admitted_at",
            *_student_sort_order_by(sort_mode, include_class_group=False),
        )
    )
    return render(
        request,
        "employees/it_support_pending_admissions.html",
        {
            "active_nav": "dashboard",
            "pending_students": students,
            "pending_admission_count": len(students),
            **_student_management_nav_context(active_tool="pending-admissions"),
            **_student_sort_template_context(request),
        },
    )


@login_required
def it_support_pending_admission_detail(request, student_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    student = get_object_or_404(
        _pending_admission_queryset(),
        pk=student_id,
    )
    return render(
        request,
        "employees/it_support_pending_admission_detail.html",
        {
            "active_nav": "dashboard",
            "student": student,
            **_student_management_nav_context(active_tool="pending-admissions"),
        },
    )


@login_required
@require_POST
def approve_workspace_student(request, student_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    student = get_object_or_404(
        Student.objects.select_related("parent_guardian"),
        pk=student_id,
    )
    if student.is_suspended:
        error(request, f"{student.display_name} is suspended and cannot be activated.")
        return _redirect_pending_admissions()
    if student.is_active:
        success(request, f"{student.display_name} is already active.")
        return _redirect_pending_admissions()

    student.is_active = True
    student.save(update_fields=["is_active"])
    parent = student.parent_guardian
    if parent is not None and not parent.is_active:
        parent.is_active = True
        parent.save(update_fields=["is_active"])
    success(
        request,
        f"{student.display_name} was approved and portal access is now active.",
    )
    return _redirect_pending_admissions()


@login_required
def workspace_student_profile(request, student_id):
    student = get_object_or_404(Student.objects.select_related("parent_guardian"), pk=student_id)
    role = workspace_role(request)
    return render(
        request,
        "employees/student_profile.html",
        {
            "active_nav": "dashboard",
            "active_module": "student-management" if role == Employee.Role.IT_SUPPORT else "",
            "student": student,
            "can_manage_students": role == Employee.Role.IT_SUPPORT,
        },
    )


@login_required
def workspace_student_profile_legacy(request, student_id):
    return redirect(
        "employees:workspace_student_profile",
        student_id=student_id,
    )


@login_required
@require_POST
def update_workspace_student(request, student_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    student = get_object_or_404(Student.objects.select_related("parent_guardian"), pk=student_id)
    form = StudentWorkspaceForm(request.POST, request.FILES, student=student)
    if form.is_valid():
        student = form.save()
        success(request, f"{student.display_name} was updated.")
    else:
        first_error = next(iter(form.errors.values()))[0]
        error(request, first_error)
    return _redirect_student_management()


@login_required
@require_POST
def toggle_workspace_student_status(request, student_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    student = get_object_or_404(Student, pk=student_id)
    student.is_suspended = not student.is_suspended
    student.is_active = not student.is_suspended
    student.save(update_fields=["is_suspended", "is_active"])
    success(
        request,
        f"{student.display_name} was {'suspended' if student.is_suspended else 'unsuspended'}.",
    )
    return _redirect_student_management()


@login_required
@require_POST
def delete_workspace_student(request, student_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    student = get_object_or_404(Student.objects.select_related("parent_guardian"), pk=student_id)
    parent = student.parent_guardian
    name = student.display_name
    student.delete()
    if parent is not None and not parent.students.exists():
        parent.delete()
    success(request, f"{name} was deleted from the system.")
    return _redirect_student_management()


def _active_workflow_exam():
    """Return the single exam currently progressing through the workflow."""
    return (
        GeneratedExamTimetable.objects.filter(
            status__in=GeneratedExamTimetable.ACTIVE_WORKFLOW_STATUSES
        )
        .order_by("-created_at")
        .first()
    )


def _in_session_exam():
    return (
        GeneratedExamTimetable.objects.filter(status=GeneratedExamTimetable.Status.IN_SESSION)
        .order_by("-created_at")
        .first()
    )


def _initial_exam_status():
    if _active_workflow_exam() is not None:
        return GeneratedExamTimetable.Status.SCHEDULED
    return GeneratedExamTimetable.Status.IN_SESSION


def _can_change_exam_status(exam):
    if exam.status == GeneratedExamTimetable.Status.PUBLISHED:
        return False
    if exam.status == GeneratedExamTimetable.Status.SCHEDULED:
        return _active_workflow_exam() is None
    return exam.status in GeneratedExamTimetable.ACTIVE_WORKFLOW_STATUSES


def _can_set_as_current_exam(exam):
    return exam.status != GeneratedExamTimetable.Status.PUBLISHED


def _demote_other_active_exams(exam):
    GeneratedExamTimetable.objects.exclude(pk=exam.pk).filter(
        status__in=GeneratedExamTimetable.ACTIVE_WORKFLOW_STATUSES
    ).update(status=GeneratedExamTimetable.Status.SCHEDULED)


def _is_current_exam(exam):
    return exam.status in GeneratedExamTimetable.ACTIVE_WORKFLOW_STATUSES


def _annotate_exam_workflow_flags(exam, active=None):
    exam.is_current_exam = _is_current_exam(exam)
    exam.can_set_current = _can_set_as_current_exam(exam)
    return exam


def _current_exam_for_dashboard():
    for status in GeneratedExamTimetable.ACTIVE_WORKFLOW_STATUSES:
        exam = (
            GeneratedExamTimetable.objects.filter(status=status)
            .order_by("-created_at")
            .first()
        )
        if exam is not None:
            return exam
    today = timezone.localdate()
    in_window = (
        GeneratedExamTimetable.objects.filter(start_date__lte=today, end_date__gte=today)
        .order_by("-created_at")
        .first()
    )
    if in_window is not None:
        return in_window
    active = (
        GeneratedExamTimetable.objects.exclude(status=GeneratedExamTimetable.Status.PUBLISHED)
        .order_by("-created_at")
        .first()
    )
    if active is not None:
        return active
    return GeneratedExamTimetable.objects.order_by("-created_at").first()


def _exam_today_schedule(generation, today=None):
    today = today or timezone.localdate()
    sittings = list(
        GeneratedExamSitting.objects.filter(generation=generation, exam_date=today)
        .select_related(
            "academic_class",
            "academic_level",
            "learning_area",
            "supervisor",
        )
        .order_by("start_time", "academic_level__order", "academic_class__order", "academic_class__name")
    )
    if not sittings:
        return None

    periods = OrderedDict()
    for sitting in sittings:
        period_key = (sitting.period_name, to_minutes(sitting.start_time))
        period = periods.setdefault(
            period_key,
            {
                "name": sitting.period_name,
                "start_label": sitting.start_time.strftime("%H:%M"),
                "end_label": sitting.end_time.strftime("%H:%M"),
                "sittings": [],
            },
        )
        period["sittings"].append(
            {
                "academic_class": sitting.academic_class,
                "learning_area": sitting.learning_area,
                "supervisor": sitting.supervisor,
                "level": sitting.academic_level,
            }
        )
    return {
        "date": today,
        "date_label": today.strftime("%A %d %b %Y"),
        "periods": list(periods.values()),
        "sitting_count": len(sittings),
    }


def _exam_marking_mark_timeline(generation):
    mark_rows = list(
        ExamMark.objects.filter(generation=generation).values_list(
            "student_id", "learning_area_id", "updated_at"
        )
    )
    mark_keys = set()
    mark_dates_by_key = defaultdict(list)
    for student_id, subject_id, updated_at in mark_rows:
        mark_keys.add((student_id, subject_id))
        mark_dates_by_key[(student_id, subject_id)].append(timezone.localdate(updated_at))
    return mark_keys, mark_dates_by_key


def _exam_marking_progress_metrics(slot_keys, mark_keys, mark_dates_by_key):
    expected = len(slot_keys)
    entered = sum(1 for key in slot_keys if key in mark_keys)
    percent = round((entered / expected) * 100) if expected else 0

    all_dates = sorted(
        {
            mark_date
            for key in slot_keys
            for mark_date in mark_dates_by_key.get(key, [])
        }
    )
    if not all_dates:
        trend_values = [0, percent] if percent else [0]
    else:
        trend_values = []
        for mark_date in all_dates:
            count = sum(
                1
                for key in slot_keys
                if key in mark_keys and any(item <= mark_date for item in mark_dates_by_key.get(key, []))
            )
            trend_values.append(round((count / expected) * 100) if expected else 0)
        if not trend_values or trend_values[-1] != percent:
            trend_values.append(percent)
    return entered, expected, percent, trend_values


def _exam_marking_allocation_slots(generation):
    level_ids = list(generation.academic_levels.values_list("id", flat=True))
    if not level_ids:
        return []

    allocations = list(
        ClassSubjectAllocation.objects.filter(
            academic_class__academic_level_id__in=level_ids,
            academic_class__status=AcademicClass.Status.ACTIVE,
            teacher__isnull=False,
        )
        .select_related(
            "teacher",
            "academic_class",
            "academic_class__academic_level",
            "learning_area",
        )
        .order_by("teacher__last_name", "teacher__first_name")
    )
    slots = []
    for allocation in allocations:
        teacher = allocation.teacher
        level = allocation.academic_class.academic_level
        exam_subject_ids = {subject.id for subject in _exam_record_subjects(level, allocation.academic_class)}
        if allocation.learning_area_id not in exam_subject_ids:
            continue
        student_ids = list(
            _students_in_academic_level(level, allocation.academic_class).values_list("id", flat=True)
        )
        if not student_ids:
            continue
        slots.append(
            {
                "teacher_id": teacher.id,
                "teacher": teacher,
                "class_name": allocation.academic_class.name,
                "subject_code": allocation.learning_area.code,
                "level_name": level.name,
                "subject_id": allocation.learning_area_id,
                "student_ids": student_ids,
            }
        )
    return slots


def _exam_marking_teacher_progress(generation):
    from apps.employees.system_performance import _build_sparkline

    slots = _exam_marking_allocation_slots(generation)
    if not slots:
        return []

    mark_keys, mark_dates_by_key = _exam_marking_mark_timeline(generation)
    teacher_slots = defaultdict(list)
    teacher_map = {}
    for slot in slots:
        teacher_map[slot["teacher_id"]] = slot["teacher"]
        teacher_slots[slot["teacher_id"]].append(slot)

    results = []
    for teacher_id, teacher_slot_list in teacher_slots.items():
        teacher = teacher_map[teacher_id]
        allocation_rows = []
        all_slot_keys = []

        for slot in sorted(teacher_slot_list, key=lambda item: (item["class_name"], item["subject_code"])):
            slot_keys = [(student_id, slot["subject_id"]) for student_id in slot["student_ids"]]
            all_slot_keys.extend(slot_keys)
            entered, expected, percent, trend_values = _exam_marking_progress_metrics(
                slot_keys, mark_keys, mark_dates_by_key
            )
            allocation_rows.append(
                {
                    "class_name": slot["class_name"],
                    "subject_code": slot["subject_code"],
                    "level_name": slot["level_name"],
                    "entered": entered,
                    "expected": expected,
                    "percent": percent,
                    "trend": _build_sparkline(trend_values, width=100, height=28, pad=2),
                }
            )

        entered, expected, percent, trend_values = _exam_marking_progress_metrics(
            all_slot_keys, mark_keys, mark_dates_by_key
        )
        results.append(
            {
                "teacher": teacher,
                "display_name": f"{teacher.first_name} {teacher.last_name}".strip(),
                "expected": expected,
                "entered": entered,
                "percent": percent,
                "trend": _build_sparkline(trend_values, width=120, height=32, pad=2),
                "allocation_count": len(allocation_rows),
                "allocations": allocation_rows,
            }
        )
    results.sort(key=lambda item: (-item["percent"], item["display_name"]))
    return results


def _exam_marking_mark_keys(generation):
    return _exam_marking_mark_timeline(generation)[0]


def _exam_marking_class_subject_progress(generation):
    level_ids = list(generation.academic_levels.values_list("id", flat=True))
    if not level_ids:
        return []

    allocations = list(
        ClassSubjectAllocation.objects.filter(
            academic_class__academic_level_id__in=level_ids,
            academic_class__status=AcademicClass.Status.ACTIVE,
            teacher__isnull=False,
        )
        .select_related(
            "teacher",
            "academic_class",
            "academic_class__academic_level",
            "learning_area",
        )
        .order_by(
            "academic_class__academic_level__order",
            "academic_class__order",
            "academic_class__name",
            "learning_area__display_order",
            "learning_area__name",
        )
    )
    if not allocations:
        return []

    mark_keys = _exam_marking_mark_keys(generation)
    results = []
    for allocation in allocations:
        level = allocation.academic_class.academic_level
        exam_subject_ids = {subject.id for subject in _exam_record_subjects(level, allocation.academic_class)}
        if allocation.learning_area_id not in exam_subject_ids:
            continue
        student_ids = list(
            _students_in_academic_level(level, allocation.academic_class).values_list("id", flat=True)
        )
        if not student_ids:
            continue
        expected = len(student_ids)
        entered = sum(
            1
            for student_id in student_ids
            if (student_id, allocation.learning_area_id) in mark_keys
        )
        percent = round((entered / expected) * 100) if expected else 0
        teacher = allocation.teacher
        results.append(
            {
                "academic_class": allocation.academic_class,
                "class_name": allocation.academic_class.name,
                "level_name": level.name,
                "subject": allocation.learning_area,
                "subject_code": allocation.learning_area.code,
                "teacher": teacher,
                "teacher_name": f"{teacher.first_name} {teacher.last_name}".strip(),
                "expected": expected,
                "entered": entered,
                "percent": percent,
            }
        )
    results.sort(
        key=lambda item: (
            -item["percent"],
            item["class_name"],
            item["subject_code"],
        )
    )
    return results


def _exam_class_marks_analytics(generation):
    classes = _exam_active_classes(generation)
    results = []
    for academic_class in classes:
        level = academic_class.academic_level
        students = list(_students_in_academic_level(level, academic_class))
        subjects = _exam_record_subjects(level, academic_class)
        if not students or not subjects:
            continue
        out_of_by_subject = _exam_record_out_of(level, subjects)
        marks_lookup = _exam_record_mark_lookup(generation, students, subjects)
        _attach_exam_mark_cells(students, subjects, marks_lookup, out_of_by_subject)
        subject_means = _exam_record_subject_means(students, subjects)
        expected = len(students) * len(subjects)
        entered = sum(
            1
            for student in students
            for subject in subjects
            if _exam_mark_entry_raw(marks_lookup.get((student.id, subject.id))) not in (None, "")
        )
        valid_means = [item["percent_mean"] for item in subject_means if item["percent_mean"] is not None]
        results.append(
            {
                "academic_class": academic_class,
                "students_count": len(students),
                "subjects_count": len(subjects),
                "expected_marks": expected,
                "entered_marks": entered,
                "completion_percent": round((entered / expected) * 100) if expected else 0,
                "subject_means": subject_means,
                "class_mean": round(sum(valid_means) / len(valid_means)) if valid_means else None,
            }
        )
    return results


def _build_exam_management_dashboard():
    exam = _current_exam_for_dashboard()
    if exam is None:
        return {"current_exam": None}

    exam = (
        GeneratedExamTimetable.objects.select_related("academic_year", "academic_term")
        .prefetch_related("academic_levels")
        .get(pk=exam.pk)
    )
    dashboard = {
        "current_exam": exam,
        "exam_title": _exam_record_title(exam),
        "status": exam.status,
        "status_label": exam.get_status_display(),
    }
    if exam.status == GeneratedExamTimetable.Status.IN_SESSION:
        dashboard["today_schedule"] = _exam_today_schedule(exam)
    if exam.status == GeneratedExamTimetable.Status.MARKING:
        dashboard["teacher_progress"] = _exam_marking_teacher_progress(exam)
        if exam.deadline:
            dashboard["marking_deadline"] = exam.deadline
    if exam.status in (
        GeneratedExamTimetable.Status.ANALYSING,
        GeneratedExamTimetable.Status.PUBLISHED,
    ):
        dashboard["class_analytics"] = _exam_class_marks_analytics(exam)
    return dashboard


@login_required
def it_support_curriculum_section(request, section):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = _it_support_curriculum_section(section)
    if current is None:
        return redirect("employees:it_support_module", module="curriculum-management")
    if current["slug"] == "learning-management":
        template = "employees/it_support_learning.html"
    elif current["slug"] == "e-learning-management":
        template = "employees/it_support_elearning.html"
    elif current["slug"] == "exam-management":
        template = "employees/it_support_exam.html"
    else:
        template = "employees/it_support_curriculum_section.html"
    context = {
        "active_nav": "dashboard",
        "section": current,
        "learning_pages": IT_SUPPORT_LEARNING_PAGES,
        "elearning_pages": IT_SUPPORT_ELEARNING_PAGES,
        "exam_pages": IT_SUPPORT_EXAM_PAGES,
        "active_elearning_tool": None,
    }
    if current["slug"] == "exam-management":
        context["exam_dashboard"] = _build_exam_management_dashboard()
    return render(request, template, context)


@login_required
def it_support_elearning_page(request, page):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = _it_support_elearning_page(page)
    if current is None:
        return redirect("employees:it_support_curriculum_section", section="e-learning-management")
    if current["slug"] == "allocate-subjects":
        return elearning_subject_allocation(request, current)
    if current["slug"] == "timetable-generation":
        return elearning_timetable_generation(request, current)
    if current["slug"] == "attendance":
        return elearning_attendance(request, current)
    if current["slug"] == "assessments":
        return elearning_assessments(request, current)
    if current["slug"] == "learning-materials":
        return elearning_learning_materials(request, current)
    return redirect("employees:it_support_curriculum_section", section="e-learning-management")


def _elearning_subject_allocation_levels():
    active_subjects = LearningArea.objects.filter(status=LearningArea.Status.ACTIVE).order_by(
        "display_order", "name"
    )
    levels = list(
        AcademicLevel.objects.filter(status=AcademicLevel.Status.ACTIVE)
        .prefetch_related(Prefetch("learning_areas", queryset=active_subjects))
        .order_by("order", "name")
    )
    level_ids = [level.id for level in levels]
    allocations = {
        (item.academic_level_id, item.learning_area_id): item.teacher_id
        for item in ELearningSubjectAllocation.objects.filter(academic_level_id__in=level_ids)
    }
    for level in levels:
        subjects = list(level.learning_areas.all())
        level.allocation_rows = [
            {
                "subject": subject,
                "field_name": f"teacher_{level.id}_{subject.id}",
                "teacher_id": allocations.get((level.id, subject.id)),
            }
            for subject in subjects
        ]
    return levels


@login_required
@require_http_methods(["GET", "POST"])
def elearning_subject_allocation(request, page=None):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = page or _it_support_elearning_page("allocate-subjects")
    teachers = list(_approved_teachers())
    teacher_ids = {teacher.id for teacher in teachers}

    if request.method == "POST":
        level = get_object_or_404(
            AcademicLevel,
            pk=request.POST.get("level_id"),
            status=AcademicLevel.Status.ACTIVE,
        )
        subjects = list(level.learning_areas.filter(status=LearningArea.Status.ACTIVE))
        subject_ids = {subject.id for subject in subjects}

        with transaction.atomic():
            for subject in subjects:
                raw_teacher_id = (request.POST.get(f"teacher_{level.id}_{subject.id}") or "").strip()
                if not raw_teacher_id:
                    ELearningSubjectAllocation.objects.filter(
                        academic_level=level,
                        learning_area=subject,
                    ).delete()
                    continue
                try:
                    teacher_id = int(raw_teacher_id)
                except ValueError:
                    continue
                if teacher_id not in teacher_ids:
                    continue
                ELearningSubjectAllocation.objects.update_or_create(
                    academic_level=level,
                    learning_area=subject,
                    defaults={"teacher_id": teacher_id},
                )
                # Keep existing sessions; only move the teacher so collisions
                # can be highlighted in red instead of wiping the grid.
                GeneratedELearningLesson.objects.filter(
                    academic_level=level,
                    learning_area=subject,
                ).update(teacher_id=teacher_id)
            ELearningSubjectAllocation.objects.filter(academic_level=level).exclude(
                learning_area_id__in=subject_ids
            ).delete()

        success(request, f"E-learning subject allocations saved for {level.name}.")
        return redirect("employees:it_support_elearning_page", page="allocate-subjects")

    levels = _elearning_subject_allocation_levels()
    return render(
        request,
        "employees/it_support_elearning_subject_allocation.html",
        {
            "active_nav": "dashboard",
            "page": current,
            "active_elearning_tool": "allocate-subjects",
            "teachers": teachers,
            "level_groups": group_academic_levels_by_category(levels),
            "elearning_pages": IT_SUPPORT_ELEARNING_PAGES,
        },
    )


def _elearning_timetable_generation_levels():
    teacher_ids = _active_teacher_ids()
    active_subjects = LearningArea.objects.filter(status=LearningArea.Status.ACTIVE).order_by(
        "display_order", "name"
    )
    levels = list(
        AcademicLevel.objects.filter(status=AcademicLevel.Status.ACTIVE)
        .prefetch_related(
            Prefetch("learning_areas", queryset=active_subjects),
            Prefetch(
                "learning_schedule_profiles",
                queryset=LearningScheduleProfile.objects.filter(
                    kind=LearningScheduleProfile.Kind.ELEARNING
                )
                .prefetch_related("activities")
                .order_by("category", "name", "id"),
            ),
        )
        .order_by("order", "name")
    )
    level_ids = [level.id for level in levels]
    allocations = {
        (item.academic_level_id, item.learning_area_id): item.teacher_id
        for item in ELearningSubjectAllocation.objects.filter(
            academic_level_id__in=level_ids,
            teacher_id__in=teacher_ids,
        )
    }
    for level in levels:
        subjects = list(level.learning_areas.all())
        missing = sum(
            1
            for subject in subjects
            if allocations.get((level.id, subject.id)) not in teacher_ids
        )
        level.generation_subjects = subjects
        level.missing_allocations = missing
        profile = resolve_elearning_schedule_profile(level)
        slots = lesson_slots_from_profile(
            profile,
            period_label="Session",
            start_caption="first session",
            end_caption="session end time",
        )
        level.schedule_profile = profile
        level.schedule_slots = slots
        level.schedule_days = sorted({slot["weekday"] for slot in slots}, key=DAY_ORDER.index)
        level.schedule_periods = len({(slot["start"], slot["end"], slot["period_name"]) for slot in slots})
        allocations_ready = bool(subjects and missing == 0)
        settings_ready = bool(profile and slots)
        level.is_viable = allocations_ready and settings_ready
        if not subjects:
            level.viability_reason = "Link at least one active subject."
        elif missing:
            level.viability_reason = (
                f"{missing} subject{'' if missing == 1 else 's'} still need an active teacher."
            )
        elif not profile:
            level.viability_reason = "Add this level to an e-learning timetable settings profile."
        elif not slots:
            level.viability_reason = (
                "Complete e-learning timetable settings so session periods can be generated."
            )
        else:
            level.viability_reason = (
                f"{profile.name}: {len(level.schedule_days)} study "
                f"day{'' if len(level.schedule_days) == 1 else 's'}, "
                f"{level.schedule_periods} session{'' if level.schedule_periods == 1 else 's'} per day."
            )
    return levels, allocations, teacher_ids


def _generate_elearning_lessons_for_levels(generation, levels, allocations, teacher_ids):
    level_plans = build_elearning_level_plans(levels, allocations, teacher_ids)
    placements, total_slots = generate_timetable_plan(level_plans)
    created = persist_elearning_timetable_plan(generation, placements)
    return created, total_slots


def _elearning_timetable_cell(lesson, colliding_ids):
    return {
        "lesson": lesson,
        "is_blank": lesson is None,
        "is_collision": bool(lesson and lesson.id in colliding_ids),
    }


def _elearning_lesson_times_overlap(left, right):
    if not left or not right:
        return False
    if left.weekday != right.weekday:
        return False
    return to_minutes(left.start_time) < to_minutes(right.end_time) and to_minutes(
        right.start_time
    ) < to_minutes(left.end_time)


def _colliding_elearning_lesson_ids(lessons):
    colliding = set()
    items = list(lessons)
    for index, current in enumerate(items):
        for other in items[index + 1 :]:
            if current.teacher_id != other.teacher_id:
                continue
            if _elearning_lesson_times_overlap(current, other):
                colliding.add(current.id)
                colliding.add(other.id)
    return colliding


def _generated_elearning_timetables(levels):
    level_ids = [level.id for level in levels]
    lessons = list(
        GeneratedELearningLesson.objects.filter(academic_level_id__in=level_ids)
        .select_related("academic_level", "learning_area", "teacher")
        .order_by("academic_level__order", "weekday", "start_time")
    )
    colliding_ids = _colliding_elearning_lesson_ids(lessons)
    by_level = {}
    for lesson in lessons:
        by_level.setdefault(lesson.academic_level_id, []).append(lesson)

    groups = []
    for level in levels:
        level_lessons = by_level.get(level.id, [])
        if not level_lessons:
            continue
        slots = list(getattr(level, "schedule_slots", []) or [])
        if slots:
            days = []
            seen_days = set()
            periods = []
            seen_periods = set()
            for slot in slots:
                if slot["weekday"] not in seen_days:
                    seen_days.add(slot["weekday"])
                    days.append(slot["weekday"])
                period_key = (slot["start"], slot["end"], slot["period_name"])
                if period_key not in seen_periods:
                    seen_periods.add(period_key)
                    periods.append(
                        {
                            "name": slot["period_name"],
                            "start": slot["start"],
                            "end": slot["end"],
                            "start_label": f"{slot['start'] // 60:02d}:{slot['start'] % 60:02d}",
                            "end_label": f"{slot['end'] // 60:02d}:{slot['end'] % 60:02d}",
                        }
                    )
        else:
            days = [day for day in DAY_ORDER if any(item.weekday == day for item in level_lessons)]
            periods = []
            seen_periods = set()
            for lesson in sorted(level_lessons, key=lambda item: item.start_time):
                start = to_minutes(lesson.start_time)
                end = to_minutes(lesson.end_time)
                period_key = (start, end, lesson.period_name)
                if period_key in seen_periods:
                    continue
                seen_periods.add(period_key)
                periods.append(
                    {
                        "name": lesson.period_name,
                        "start": start,
                        "end": end,
                        "start_label": lesson.start_time.strftime("%H:%M"),
                        "end_label": lesson.end_time.strftime("%H:%M"),
                    }
                )
        lookup = {
            (lesson.weekday, to_minutes(lesson.start_time)): lesson for lesson in level_lessons
        }
        rows = []
        for day in days:
            cells = []
            for period in periods:
                lesson = lookup.get((day, period["start"]))
                cells.append(_elearning_timetable_cell(lesson, colliding_ids))
            rows.append(
                {
                    "day_code": day,
                    "day_label": WEEKDAY_LABELS.get(day, day),
                    "cells": cells,
                }
            )
        groups.append(
            {
                "level": level,
                "lesson_count": len(level_lessons),
                "periods": periods,
                "rows": rows,
            }
        )
    return groups


@login_required
@require_http_methods(["GET", "POST"])
def elearning_timetable_generation(request, page=None):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = page or _it_support_elearning_page("timetable-generation")
    levels, allocations, teacher_ids = _elearning_timetable_generation_levels()
    viable_ids = {level.id for level in levels if level.is_viable}
    open_generate_modal = False
    if request.method == "GET" and request.GET.get("generate"):
        open_generate_modal = True

    if request.method == "POST":
        selected_ids = []
        for raw_id in request.POST.getlist("level_id"):
            try:
                selected_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        selected_ids = [level_id for level_id in selected_ids if level_id in viable_ids]
        if not selected_ids:
            error(request, "Select at least one viable academic level to generate an e-learning timetable.")
            open_generate_modal = True
        else:
            selected_levels = [level for level in levels if level.id in selected_ids]
            with transaction.atomic():
                GeneratedELearningLesson.objects.filter(
                    academic_level_id__in=selected_ids
                ).delete()
                generation = GeneratedELearningTimetable.objects.create(created_by=request.user)
                generation.academic_levels.set(selected_levels)
                lesson_count, total_slots = _generate_elearning_lessons_for_levels(
                    generation, selected_levels, allocations, teacher_ids
                )
            names = ", ".join(level.name for level in selected_levels)
            blank_count = max(total_slots - lesson_count, 0)
            if blank_count:
                detail = (
                    f"{lesson_count} session{'' if lesson_count == 1 else 's'} placed, "
                    f"{blank_count} left blank to avoid teacher collisions."
                )
            else:
                detail = (
                    f"{lesson_count} session{'' if lesson_count == 1 else 's'} created "
                    "with no teacher collisions."
                )
            success(request, f"E-learning timetable generated for {names}. {detail}")
            return redirect("employees:it_support_elearning_page", page="timetable-generation")

    return render(
        request,
        "employees/it_support_elearning_timetable_generation.html",
        {
            "active_nav": "dashboard",
            "page": current,
            "active_elearning_tool": "timetable-generation",
            "elearning_pages": IT_SUPPORT_ELEARNING_PAGES,
            "level_groups": group_academic_levels_by_category(levels),
            "viable_count": len(viable_ids),
            "open_generate_modal": open_generate_modal,
            "timetable_groups": _generated_elearning_timetables(levels),
        },
    )


@login_required
def elearning_attendance(request, page=None):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = page or _it_support_elearning_page("attendance")
    return render(
        request,
        "employees/it_support_elearning_attendance.html",
        {
            "active_nav": "dashboard",
            "page": current,
            "active_elearning_tool": "attendance",
            "elearning_pages": IT_SUPPORT_ELEARNING_PAGES,
        },
    )


@login_required
def elearning_assessments(request, page=None):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = page or _it_support_elearning_page("assessments")
    return render(
        request,
        "employees/it_support_elearning_assessments.html",
        {
            "active_nav": "dashboard",
            "page": current,
            "active_elearning_tool": "assessments",
            "elearning_pages": IT_SUPPORT_ELEARNING_PAGES,
        },
    )


@login_required
def elearning_learning_materials(request, page=None):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = page or _it_support_elearning_page("learning-materials")
    return render(
        request,
        "employees/it_support_elearning_learning_materials.html",
        {
            "active_nav": "dashboard",
            "page": current,
            "active_elearning_tool": "learning-materials",
            "elearning_pages": IT_SUPPORT_ELEARNING_PAGES,
        },
    )


@login_required
def it_support_learning_page(request, page):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = _it_support_learning_page(page)
    if current is None:
        return redirect("employees:it_support_curriculum_section", section="learning-management")
    if current["slug"] == "class-management":
        return class_teacher_allocation(request, current)
    if current["slug"] == "timetable-management":
        template = "employees/it_support_timetable.html"
    else:
        template = "employees/it_support_learning_page.html"
    return render(
        request,
        template,
        {
            "active_nav": "dashboard",
            "page": current,
            "class_pages": IT_SUPPORT_CLASS_PAGES,
            "timetable_pages": IT_SUPPORT_TIMETABLE_PAGES,
        },
    )


@login_required
def it_support_class_page(request, tool):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = _it_support_class_page(tool)
    if current is None:
        return redirect("employees:it_support_learning_page", page="class-management")
    return render(
        request,
        "employees/it_support_class_page.html",
        {
            "active_nav": "dashboard",
            "page": current,
        },
    )


def _approved_teacher_queryset(*, active_only=False):
    queryset = (
        Employee.objects.filter(
            Q(role=Employee.Role.TEACHER) | Q(assigned_roles__role=Employee.Role.TEACHER),
            approval_status=Employee.ApprovalStatus.APPROVED,
        )
        .distinct()
    )
    if active_only:
        queryset = queryset.filter(is_active=True)
    return queryset


def _approved_teachers():
    return _approved_teacher_queryset().order_by("first_name", "last_name", "employee_code")


def _class_teacher_allocation_levels():
    active_classes = AcademicClass.objects.filter(status=AcademicClass.Status.ACTIVE).order_by("order", "name")
    levels = list(
        AcademicLevel.objects.filter(status=AcademicLevel.Status.ACTIVE)
        .prefetch_related(Prefetch("classes", queryset=active_classes))
        .order_by("order", "name")
    )
    for level in levels:
        classes = list(level.classes.all())
        level.allocation_classes = [
            {
                "academic_class": academic_class,
                "field_name": f"teacher_{academic_class.id}",
                "teacher_id": academic_class.class_teacher_id,
            }
            for academic_class in classes
        ]
    return levels


@login_required
@require_http_methods(["GET", "POST"])
def class_teacher_allocation(request, page=None):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = page or _it_support_learning_page("class-management")
    teachers = list(_approved_teachers())
    teacher_ids = {teacher.id for teacher in teachers}

    if request.method == "POST":
        level = get_object_or_404(
            AcademicLevel,
            pk=request.POST.get("level_id"),
            status=AcademicLevel.Status.ACTIVE,
        )
        classes = list(level.classes.filter(status=AcademicClass.Status.ACTIVE))

        with transaction.atomic():
            for academic_class in classes:
                raw_teacher_id = (request.POST.get(f"teacher_{academic_class.id}") or "").strip()
                if not raw_teacher_id:
                    if academic_class.class_teacher_id:
                        academic_class.class_teacher = None
                        academic_class.save(update_fields=["class_teacher", "updated_at"])
                    continue
                try:
                    teacher_id = int(raw_teacher_id)
                except ValueError:
                    continue
                if teacher_id not in teacher_ids:
                    continue
                if academic_class.class_teacher_id != teacher_id:
                    academic_class.class_teacher_id = teacher_id
                    academic_class.save(update_fields=["class_teacher", "updated_at"])

        success(request, f"Class teacher allocations saved for {level.name}.")
        return redirect("employees:it_support_learning_page", page="class-management")

    levels = _class_teacher_allocation_levels()
    return render(
        request,
        "employees/it_support_class_teacher_allocation.html",
        {
            "active_nav": "dashboard",
            "page": current,
            "active_class_tool": "allocate-class-teachers",
            "teachers": teachers,
            "level_groups": group_academic_levels_by_category(levels),
            "class_pages": IT_SUPPORT_CLASS_PAGES,
        },
    )


def _class_subject_allocation_levels():
    active_classes = AcademicClass.objects.filter(status=AcademicClass.Status.ACTIVE).order_by("order", "name")
    active_subjects = LearningArea.objects.filter(status=LearningArea.Status.ACTIVE).order_by(
        "display_order", "name"
    )
    levels = list(
        AcademicLevel.objects.filter(status=AcademicLevel.Status.ACTIVE)
        .prefetch_related(
            Prefetch("classes", queryset=active_classes),
            Prefetch("learning_areas", queryset=active_subjects),
        )
        .order_by("order", "name")
    )
    class_ids = [academic_class.id for level in levels for academic_class in level.classes.all()]
    allocations = {
        (item.academic_class_id, item.learning_area_id): item.teacher_id
        for item in ClassSubjectAllocation.objects.filter(academic_class_id__in=class_ids)
    }
    for level in levels:
        classes = list(level.classes.all())
        subjects = list(level.learning_areas.all())
        rows = []
        for subject in subjects:
            cells = [
                {
                    "academic_class": academic_class,
                    "field_name": f"teacher_{academic_class.id}_{subject.id}",
                    "teacher_id": allocations.get((academic_class.id, subject.id)),
                }
                for academic_class in classes
            ]
            rows.append({"subject": subject, "cells": cells})
        level.allocation_classes = classes
        level.allocation_rows = rows
    return levels


@login_required
def it_support_timetable_page(request, tool):
    denied = _require_it_support(request)
    if denied:
        return denied
    if tool == "manual-allocation":
        return learning_manual_teacher_allocation(request)
    current = _it_support_timetable_page(tool)
    if current is None:
        return redirect("employees:it_support_learning_page", page="timetable-management")
    if current["slug"] == "class-and-subject-allocation":
        return class_subject_allocation(request, current)
    if current["slug"] == "timetable-analytics":
        return timetable_analytics(request, current)
    if current["slug"] == "timetable-generation":
        return timetable_generation(request, current)
    return render(
        request,
        "employees/it_support_timetable_page.html",
        {
            "active_nav": "dashboard",
            "page": current,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def class_subject_allocation(request, page=None):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = page or _it_support_timetable_page("class-and-subject-allocation")
    teachers = list(_approved_teachers())
    teacher_ids = {teacher.id for teacher in teachers}

    if request.method == "POST":
        level = get_object_or_404(
            AcademicLevel,
            pk=request.POST.get("level_id"),
            status=AcademicLevel.Status.ACTIVE,
        )
        classes = list(level.classes.filter(status=AcademicClass.Status.ACTIVE))
        subjects = list(level.learning_areas.filter(status=LearningArea.Status.ACTIVE))
        class_ids = {academic_class.id for academic_class in classes}
        subject_ids = {subject.id for subject in subjects}

        with transaction.atomic():
            for academic_class in classes:
                for subject in subjects:
                    raw_teacher_id = (request.POST.get(f"teacher_{academic_class.id}_{subject.id}") or "").strip()
                    if not raw_teacher_id:
                        ClassSubjectAllocation.objects.filter(
                            academic_class=academic_class,
                            learning_area=subject,
                        ).delete()
                        continue
                    try:
                        teacher_id = int(raw_teacher_id)
                    except ValueError:
                        continue
                    if teacher_id not in teacher_ids:
                        continue
                    ClassSubjectAllocation.objects.update_or_create(
                        academic_class=academic_class,
                        learning_area=subject,
                        defaults={"teacher_id": teacher_id},
                    )
                    # Keep existing timetable slots; only move the teacher so collisions
                    # can be highlighted in red instead of wiping the grid.
                    GeneratedLearningLesson.objects.filter(
                        academic_class=academic_class,
                        learning_area=subject,
                    ).update(teacher_id=teacher_id)
            ClassSubjectAllocation.objects.filter(
                academic_class_id__in=class_ids,
            ).exclude(learning_area_id__in=subject_ids).delete()

        success(request, f"Subject allocations saved for {level.name}.")
        return redirect("employees:it_support_timetable_page", tool="class-and-subject-allocation")

    levels = _class_subject_allocation_levels()
    return render(
        request,
        "employees/it_support_class_subject_allocation.html",
        {
            "active_nav": "dashboard",
            "page": current,
            "active_timetable_tool": "class-and-subject-allocation",
            "teachers": teachers,
            "level_groups": group_academic_levels_by_category(levels),
        },
    )


def _active_teacher_ids():
    return set(_approved_teacher_queryset(active_only=True).values_list("id", flat=True))


def _timetable_generation_levels():
    teacher_ids = _active_teacher_ids()
    active_classes = AcademicClass.objects.filter(status=AcademicClass.Status.ACTIVE).order_by("order", "name")
    active_subjects = LearningArea.objects.filter(status=LearningArea.Status.ACTIVE).order_by(
        "display_order", "name"
    )
    levels = list(
        AcademicLevel.objects.filter(status=AcademicLevel.Status.ACTIVE)
        .prefetch_related(
            Prefetch("classes", queryset=active_classes),
            Prefetch("learning_areas", queryset=active_subjects),
            Prefetch(
                "learning_schedule_profiles",
                queryset=LearningScheduleProfile.objects.filter(
                    kind=LearningScheduleProfile.Kind.LEARNING
                )
                .prefetch_related("activities")
                .order_by("category", "name", "id"),
            ),
        )
        .order_by("order", "name")
    )
    class_ids = [academic_class.id for level in levels for academic_class in level.classes.all()]
    allocations = {
        (item.academic_class_id, item.learning_area_id): item.teacher_id
        for item in ClassSubjectAllocation.objects.filter(
            academic_class_id__in=class_ids,
            teacher_id__in=teacher_ids,
        )
    }
    for level in levels:
        classes = list(level.classes.all())
        subjects = list(level.learning_areas.all())
        missing = 0
        for academic_class in classes:
            for subject in subjects:
                if allocations.get((academic_class.id, subject.id)) not in teacher_ids:
                    missing += 1
        level.generation_classes = classes
        level.generation_subjects = subjects
        level.missing_allocations = missing
        profile = resolve_schedule_profile(level)
        slots = lesson_slots_from_profile(profile)
        level.schedule_profile = profile
        level.schedule_slots = slots
        level.schedule_days = sorted({slot["weekday"] for slot in slots}, key=DAY_ORDER.index)
        level.schedule_periods = len({(slot["start"], slot["end"], slot["period_name"]) for slot in slots})
        allocations_ready = bool(classes and subjects and missing == 0)
        settings_ready = bool(profile and slots)
        level.is_viable = allocations_ready and settings_ready
        if not classes:
            level.viability_reason = "Register at least one active class."
        elif not subjects:
            level.viability_reason = "Link at least one active subject."
        elif missing:
            level.viability_reason = f"{missing} class subject{'' if missing == 1 else 's'} still need an active teacher."
        elif not profile:
            level.viability_reason = "Add this level to a learning timetable settings profile."
        elif not slots:
            level.viability_reason = "Complete learning timetable settings so lesson periods can be generated."
        else:
            level.viability_reason = (
                f"{profile.name}: {len(level.schedule_days)} study day{'' if len(level.schedule_days) == 1 else 's'}, "
                f"{level.schedule_periods} period{'' if level.schedule_periods == 1 else 's'} per day."
            )
    return levels, allocations, teacher_ids


def _generate_lessons_for_levels(generation, levels, allocations, teacher_ids):
    class_plans = build_class_plans(levels, allocations, teacher_ids)
    placements, total_slots = generate_timetable_plan(class_plans)
    created = persist_timetable_plan(generation, placements)
    return created, total_slots


def _generate_lessons_for_level(generation, level, allocations, teacher_ids):
    created, _total = _generate_lessons_for_levels(generation, [level], allocations, teacher_ids)
    return created


def _generate_lessons_for_classes(generation, levels, class_ids, allocations, teacher_ids):
    selected_ids = set(class_ids)
    class_plans = build_class_plans(levels, allocations, teacher_ids)
    class_plans = [plan for plan in class_plans if plan["academic_class"].id in selected_ids]
    placements, total_slots = generate_timetable_plan(class_plans)
    created = persist_timetable_plan(generation, placements)
    return created, total_slots


def _learning_class_generation_viability(level, academic_class, allocations, teacher_ids):
    subjects = list(getattr(level, "generation_subjects", []))
    missing = sum(
        1
        for subject in subjects
        if allocations.get((academic_class.id, subject.id)) not in teacher_ids
    )
    profile = getattr(level, "schedule_profile", None)
    slots = list(getattr(level, "schedule_slots", []) or [])
    if not subjects:
        return False, "No active subjects linked to this level."
    if missing:
        return False, f"{missing} subject{'' if missing == 1 else 's'} still need an active teacher."
    if not profile:
        return False, "Add this level to a learning timetable settings profile."
    if not slots:
        return False, "Complete learning timetable settings so lesson periods can be generated."
    return True, "Ready to generate."


def _learning_class_timetable_grid(level, academic_class, class_lessons, colliding_ids):
    slots = list(getattr(level, "schedule_slots", []) or [])
    if slots:
        days = []
        seen_days = set()
        periods = []
        seen_periods = set()
        for slot in slots:
            if slot["weekday"] not in seen_days:
                seen_days.add(slot["weekday"])
                days.append(slot["weekday"])
            period_key = (slot["start"], slot["end"], slot["period_name"])
            if period_key not in seen_periods:
                seen_periods.add(period_key)
                periods.append(
                    {
                        "name": slot["period_name"],
                        "start": slot["start"],
                        "end": slot["end"],
                        "start_label": f"{slot['start'] // 60:02d}:{slot['start'] % 60:02d}",
                        "end_label": f"{slot['end'] // 60:02d}:{slot['end'] % 60:02d}",
                    }
                )
    elif class_lessons:
        days = [day for day in DAY_ORDER if any(item.weekday == day for item in class_lessons)]
        periods = []
        seen_periods = set()
        for lesson in sorted(class_lessons, key=lambda item: item.start_time):
            start = to_minutes(lesson.start_time)
            end = to_minutes(lesson.end_time)
            period_key = (start, end, lesson.period_name)
            if period_key in seen_periods:
                continue
            seen_periods.add(period_key)
            periods.append(
                {
                    "name": lesson.period_name,
                    "start": start,
                    "end": end,
                    "start_label": lesson.start_time.strftime("%H:%M"),
                    "end_label": lesson.end_time.strftime("%H:%M"),
                }
            )
    else:
        return {"periods": [], "rows": [], "lesson_count": 0}

    lookup = {(lesson.weekday, to_minutes(lesson.start_time)): lesson for lesson in class_lessons}
    rows = []
    for day in days:
        cells = []
        for period in periods:
            lesson = lookup.get((day, period["start"]))
            cells.append(
                _learning_timetable_cell(
                    lesson,
                    colliding_ids,
                    academic_class=academic_class,
                    day=day,
                    period=period,
                )
            )
        rows.append(
            {
                "day_code": day,
                "day_label": WEEKDAY_LABELS.get(day, day),
                "cells": cells,
            }
        )
    return {"periods": periods, "rows": rows, "lesson_count": len(class_lessons)}


def _generated_class_timetables(
    levels,
    *,
    include_all_classes=False,
    allocations=None,
    teacher_ids=None,
):
    class_ids = [
        academic_class.id
        for level in levels
        for academic_class in getattr(level, "generation_classes", [])
    ]
    lessons = list(
        GeneratedLearningLesson.objects.filter(academic_class_id__in=class_ids)
        .select_related("academic_class", "academic_level", "learning_area", "teacher")
        .order_by("academic_level__order", "academic_class__order", "weekday", "start_time")
    )
    colliding_ids = _colliding_learning_lesson_ids(lessons)
    by_class = {}
    for lesson in lessons:
        by_class.setdefault(lesson.academic_class_id, []).append(lesson)

    groups = []
    for level in levels:
        class_grids = []
        for academic_class in getattr(level, "generation_classes", []):
            class_lessons = by_class.get(academic_class.id, [])
            if not class_lessons and not include_all_classes:
                continue
            grid = _learning_class_timetable_grid(level, academic_class, class_lessons, colliding_ids)
            class_entry = {
                "academic_class": academic_class,
                "lesson_count": grid["lesson_count"],
                "periods": grid["periods"],
                "rows": grid["rows"],
                "has_generated_timetable": bool(class_lessons),
            }
            if include_all_classes and allocations is not None and teacher_ids is not None:
                is_viable, viability_reason = _learning_class_generation_viability(
                    level, academic_class, allocations, teacher_ids
                )
                class_entry["is_viable"] = is_viable
                class_entry["viability_reason"] = viability_reason
            class_grids.append(class_entry)
        if class_grids:
            groups.append({"level": level, "classes": class_grids})
    return groups


def _learning_slot_key(class_id, weekday, start_minutes):
    return f"{class_id}:{weekday}:{start_minutes}"


def _learning_timetable_cell(lesson, colliding_ids, *, academic_class=None, day=None, period=None):
    cell = {
        "lesson": lesson,
        "is_blank": lesson is None,
        "is_collision": bool(lesson and lesson.id in colliding_ids),
    }
    if lesson is None and academic_class is not None and day is not None and period is not None:
        cell["slot_key"] = _learning_slot_key(academic_class.id, day, period["start"])
        cell["slot"] = {
            "class_id": academic_class.id,
            "weekday": day,
            "period_name": period["name"],
            "start": period["start"],
            "end": period["end"],
        }
    return cell


def _learning_lesson_times_overlap(left, right):
    if not left or not right:
        return False
    if left.weekday != right.weekday:
        return False
    return to_minutes(left.start_time) < to_minutes(right.end_time) and to_minutes(right.start_time) < to_minutes(
        left.end_time
    )


def _colliding_learning_lesson_ids(lessons):
    colliding = set()
    items = list(lessons)
    for index, current in enumerate(items):
        for other in items[index + 1 :]:
            if current.teacher_id != other.teacher_id:
                continue
            if _learning_lesson_times_overlap(current, other):
                colliding.add(current.id)
                colliding.add(other.id)
    return colliding


def _allocated_pairs_by_class(class_to_level):
    pairs_by_class = {}
    seen = {}
    allocations = (
        ClassSubjectAllocation.objects.filter(
            academic_class_id__in=class_to_level,
            teacher_id__in=_active_teacher_ids(),
        )
        .select_related("learning_area", "teacher")
        .order_by(
            "learning_area__display_order",
            "learning_area__name",
            "teacher__first_name",
            "teacher__last_name",
        )
    )
    for allocation in allocations:
        class_id = allocation.academic_class_id
        if class_id not in class_to_level:
            continue
        key = (allocation.learning_area_id, allocation.teacher_id)
        if class_id not in pairs_by_class:
            pairs_by_class[class_id] = []
            seen[class_id] = set()
        if key in seen[class_id]:
            continue
        seen[class_id].add(key)
        pairs_by_class[class_id].append((allocation.learning_area, allocation.teacher))
    return pairs_by_class


def _learning_busy_teachers_for_session(session, lessons):
    busy = {}
    for other in lessons:
        if other.teacher_id is None:
            continue
        if getattr(session, "id", None) and other.id == session.id:
            continue
        if not _learning_lesson_times_overlap(session, other):
            continue
        busy[other.teacher_id] = other.academic_class.name
    return busy


def _learning_allocation_pair_options(pairs, busy, selected_subject_id=None, selected_teacher_id=None):
    options = []
    for subject, teacher in pairs:
        busy_class = busy.get(teacher.id)
        options.append(
            {
                "subject_id": subject.id,
                "teacher_id": teacher.id,
                "subject_code": subject.code,
                "subject_name": subject.name,
                "teacher_name": f"{teacher.first_name} {teacher.last_name}".strip(),
                "available": busy_class is None,
                "busy_class": busy_class or "",
                "selected": (
                    subject.id == selected_subject_id and teacher.id == selected_teacher_id
                ),
            }
        )
    return options


def _learning_allocation_options_by_lesson(lessons, pairs_by_class):
    choices = {}
    for lesson in lessons:
        busy = _learning_busy_teachers_for_session(lesson, lessons)
        pairs = list(pairs_by_class.get(lesson.academic_class_id, []))
        pair_keys = {(subject.id, teacher.id) for subject, teacher in pairs}
        current_key = (lesson.learning_area_id, lesson.teacher_id)
        if current_key not in pair_keys and lesson.learning_area_id and lesson.teacher_id:
            pairs.append((lesson.learning_area, lesson.teacher))
        choices[str(lesson.id)] = _learning_allocation_pair_options(
            pairs,
            busy,
            selected_subject_id=lesson.learning_area_id,
            selected_teacher_id=lesson.teacher_id,
        )
    return choices


def _learning_allocation_options_by_slot(timetable_groups, lessons, pairs_by_class):
    choices = {}
    for group in timetable_groups:
        for grid in group["classes"]:
            academic_class = grid["academic_class"]
            pairs = pairs_by_class.get(academic_class.id, [])
            if not pairs:
                continue
            for row in grid["rows"]:
                for cell in row["cells"]:
                    slot_key = cell.get("slot_key")
                    slot = cell.get("slot")
                    if not slot_key or not slot:
                        continue
                    session = SimpleNamespace(
                        id=None,
                        weekday=slot["weekday"],
                        start_time=minutes_to_time(slot["start"]),
                        end_time=minutes_to_time(slot["end"]),
                        academic_class_id=slot["class_id"],
                    )
                    busy = _learning_busy_teachers_for_session(session, lessons)
                    choices[slot_key] = _learning_allocation_pair_options(pairs, busy)
    return choices


def _learning_generation_for_class(class_id, level_id):
    existing = (
        GeneratedLearningLesson.objects.filter(academic_class_id=class_id)
        .select_related("generation")
        .order_by("-id")
        .first()
    )
    if existing:
        return existing.generation
    return (
        GeneratedLearningTimetable.objects.filter(academic_levels__id=level_id)
        .order_by("-created_at")
        .first()
    )


def _learning_level_ids_with_generated_timetables(levels):
    class_ids = [
        academic_class.id
        for level in levels
        for academic_class in getattr(level, "generation_classes", [])
    ]
    if not class_ids:
        return set()
    return set(
        GeneratedLearningLesson.objects.filter(academic_class_id__in=class_ids)
        .values_list("academic_level_id", flat=True)
        .distinct()
    )


def _learning_class_ids_with_generated_timetables(levels):
    class_ids = [
        academic_class.id
        for level in levels
        for academic_class in getattr(level, "generation_classes", [])
    ]
    if not class_ids:
        return set()
    return set(
        GeneratedLearningLesson.objects.filter(academic_class_id__in=class_ids)
        .values_list("academic_class_id", flat=True)
        .distinct()
    )


def _reset_learning_timetables_for_levels(levels, selected_ids):
    selected_levels = [level for level in levels if level.id in selected_ids]
    class_ids = [
        academic_class.id
        for level in selected_levels
        for academic_class in level.generation_classes
    ]
    deleted_count, _selected_classes = _reset_learning_timetables_for_classes(levels, class_ids)
    return deleted_count, selected_levels


def _reset_learning_timetables_for_classes(levels, class_ids):
    class_id_set = set(class_ids)
    affected_level_ids = set()
    selected_classes = []
    for level in levels:
        for academic_class in getattr(level, "generation_classes", []):
            if academic_class.id in class_id_set:
                affected_level_ids.add(level.id)
                selected_classes.append(academic_class)
    with transaction.atomic():
        deleted_count, _details = GeneratedLearningLesson.objects.filter(
            academic_class_id__in=class_ids
        ).delete()
        for level_id in affected_level_ids:
            if not GeneratedLearningLesson.objects.filter(academic_level_id=level_id).exists():
                for generation in GeneratedLearningTimetable.objects.filter(academic_levels__id=level_id):
                    generation.academic_levels.remove(level_id)
        GeneratedLearningTimetable.objects.annotate(lesson_count=Count("lessons")).filter(
            lesson_count=0
        ).delete()
    return deleted_count, selected_classes


def _learning_class_for_id(levels, class_id):
    for level in levels:
        for academic_class in getattr(level, "generation_classes", []):
            if academic_class.id == class_id:
                return level, academic_class
    return None, None


@login_required
@require_http_methods(["GET", "POST"])
def timetable_generation(request, page=None):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = page or _it_support_timetable_page("timetable-generation")
    levels, allocations, teacher_ids = _timetable_generation_levels()
    viable_ids = {level.id for level in levels if level.is_viable}
    resettable_ids = _learning_level_ids_with_generated_timetables(levels)
    for level in levels:
        level.has_generated_timetable = level.id in resettable_ids
    open_generate_modal = False
    open_reset_modal = False
    if request.method == "GET" and request.GET.get("generate"):
        open_generate_modal = True
    if request.method == "GET" and request.GET.get("reset"):
        open_reset_modal = True

    if request.method == "POST":
        action = (request.POST.get("action") or "generate").strip().lower()
        if action in {"generate_class", "reset_class"}:
            try:
                class_id = int((request.POST.get("class_id") or "").strip())
            except (TypeError, ValueError):
                class_id = None
            level, academic_class = _learning_class_for_id(levels, class_id)
            if academic_class is None:
                error(request, "Select a valid class to continue.")
            elif action == "reset_class":
                if class_id not in _learning_class_ids_with_generated_timetables(levels):
                    error(request, f"{academic_class.name} does not have a generated timetable to reset.")
                else:
                    deleted_count, selected_classes = _reset_learning_timetables_for_classes(
                        levels, [class_id]
                    )
                    lesson_count = max(deleted_count, 0)
                    detail = (
                        f"{lesson_count} lesson{'' if lesson_count == 1 else 's'} removed."
                        if lesson_count
                        else "No lessons were stored for this class."
                    )
                    success(request, f"Timetable reset for {academic_class.name}. {detail}")
                    return redirect("employees:it_support_timetable_page", tool="timetable-generation")
            else:
                is_viable, viability_reason = _learning_class_generation_viability(
                    level, academic_class, allocations, teacher_ids
                )
                if not is_viable:
                    error(request, f"{academic_class.name} cannot be generated yet. {viability_reason}")
                else:
                    with transaction.atomic():
                        GeneratedLearningLesson.objects.filter(academic_class_id=class_id).delete()
                        generation = _learning_generation_for_class(class_id, level.id)
                        if not generation:
                            generation = GeneratedLearningTimetable.objects.create(
                                created_by=request.user
                            )
                            generation.academic_levels.add(level)
                        lesson_count, total_slots = _generate_lessons_for_classes(
                            generation, levels, [class_id], allocations, teacher_ids
                        )
                    blank_count = max(total_slots - lesson_count, 0)
                    if blank_count:
                        detail = (
                            f"{lesson_count} lesson{'' if lesson_count == 1 else 's'} placed, "
                            f"{blank_count} left blank to avoid teacher collisions."
                        )
                    else:
                        detail = (
                            f"{lesson_count} lesson{'' if lesson_count == 1 else 's'} created "
                            "with no teacher collisions."
                        )
                    success(request, f"Timetable generated for {academic_class.name}. {detail}")
                    return redirect("employees:it_support_timetable_page", tool="timetable-generation")
        else:
            selected_ids = []
            for raw_id in request.POST.getlist("level_id"):
                try:
                    selected_ids.append(int(raw_id))
                except (TypeError, ValueError):
                    continue
            if action == "reset":
                selected_ids = [level_id for level_id in selected_ids if level_id in resettable_ids]
                if not selected_ids:
                    error(
                        request,
                        "Select at least one academic level with a generated timetable to reset.",
                    )
                    open_reset_modal = True
                else:
                    deleted_count, selected_levels = _reset_learning_timetables_for_levels(
                        levels, selected_ids
                    )
                    names = ", ".join(level.name for level in selected_levels)
                    lesson_count = max(deleted_count, 0)
                    detail = (
                        f"{lesson_count} lesson{'' if lesson_count == 1 else 's'} removed."
                        if lesson_count
                        else "No lessons were stored for the selected levels."
                    )
                    success(request, f"Timetable reset for {names}. {detail}")
                    return redirect("employees:it_support_timetable_page", tool="timetable-generation")
            else:
                selected_ids = [level_id for level_id in selected_ids if level_id in viable_ids]
                if not selected_ids:
                    error(request, "Select at least one viable academic level to generate a timetable.")
                    open_generate_modal = True
                else:
                    selected_levels = [level for level in levels if level.id in selected_ids]
                    class_ids = [
                        academic_class.id
                        for level in selected_levels
                        for academic_class in level.generation_classes
                    ]
                    with transaction.atomic():
                        GeneratedLearningLesson.objects.filter(academic_class_id__in=class_ids).delete()
                        generation = GeneratedLearningTimetable.objects.create(created_by=request.user)
                        generation.academic_levels.set(selected_levels)
                        lesson_count, total_slots = _generate_lessons_for_levels(
                            generation, selected_levels, allocations, teacher_ids
                        )
                    names = ", ".join(level.name for level in selected_levels)
                    blank_count = max(total_slots - lesson_count, 0)
                    if blank_count:
                        detail = (
                            f"{lesson_count} lesson{'' if lesson_count == 1 else 's'} placed, "
                            f"{blank_count} left blank to avoid teacher collisions."
                        )
                    else:
                        detail = f"{lesson_count} lesson{'' if lesson_count == 1 else 's'} created with no teacher collisions."
                    success(request, f"Timetable generated for {names}. {detail}")
                    return redirect("employees:it_support_timetable_page", tool="timetable-generation")

    timetable_groups = _generated_class_timetables(
        levels,
        include_all_classes=True,
        allocations=allocations,
        teacher_ids=teacher_ids,
    )
    generated_level_count = sum(
        1
        for group in timetable_groups
        if any(class_grid["has_generated_timetable"] for class_grid in group["classes"])
    )

    return render(
        request,
        "employees/it_support_timetable_generation.html",
        {
            "active_nav": "dashboard",
            "page": current,
            "active_timetable_tool": "timetable-generation",
            "level_groups": group_academic_levels_by_category(levels),
            "viable_count": len(viable_ids),
            "resettable_count": len(resettable_ids),
            "generated_level_count": generated_level_count,
            "open_generate_modal": open_generate_modal,
            "open_reset_modal": open_reset_modal,
            "timetable_groups": timetable_groups,
        },
    )


def _class_to_level_map(levels):
    class_to_level = {}
    for level in levels:
        for academic_class in getattr(level, "generation_classes", []):
            class_to_level[academic_class.id] = level.id
    return class_to_level


@login_required
@require_http_methods(["GET", "POST"])
def learning_manual_teacher_allocation(request):
    denied = _require_it_support(request)
    if denied:
        return denied
    levels, _allocations, _teacher_ids = _timetable_generation_levels()
    class_to_level = _class_to_level_map(levels)
    pairs_by_class = _allocated_pairs_by_class(class_to_level)
    class_ids = list(class_to_level)
    lessons = list(
        GeneratedLearningLesson.objects.filter(academic_class_id__in=class_ids)
        .select_related("academic_class", "learning_area", "teacher")
        .order_by("weekday", "start_time", "academic_class__order")
    )
    timetable_groups = _generated_class_timetables(levels)
    slot_meta = {}
    for group in timetable_groups:
        for grid in group["classes"]:
            academic_class = grid["academic_class"]
            for row in grid["rows"]:
                for cell in row["cells"]:
                    slot_key = cell.get("slot_key")
                    slot = cell.get("slot")
                    if not slot_key or not slot:
                        continue
                    slot_meta[slot_key] = {
                        "class_id": slot["class_id"],
                        "class_name": academic_class.name,
                        "day_label": row["day_label"],
                        "session": slot["period_name"],
                        "time": (
                            f"{slot['start'] // 60:02d}:{slot['start'] % 60:02d}"
                            f"–{slot['end'] // 60:02d}:{slot['end'] % 60:02d}"
                        ),
                        "weekday": slot["weekday"],
                        "period_name": slot["period_name"],
                        "start": slot["start"],
                        "end": slot["end"],
                    }

    if request.method == "POST":
        try:
            subject_id = int((request.POST.get("subject_id") or "").strip())
        except (TypeError, ValueError):
            subject_id = None
        try:
            teacher_id = int((request.POST.get("teacher_id") or "").strip())
        except (TypeError, ValueError):
            teacher_id = None
        raw_pair = (request.POST.get("allocation") or "").strip()
        if (subject_id is None or teacher_id is None) and ":" in raw_pair:
            raw_subject, raw_teacher = raw_pair.split(":", 1)
            try:
                subject_id = int(raw_subject)
                teacher_id = int(raw_teacher)
            except (TypeError, ValueError):
                subject_id = teacher_id = None

        slot_key = (request.POST.get("slot_key") or "").strip()
        if slot_key:
            slot = slot_meta.get(slot_key)
            if not slot:
                error(request, "Select a valid free session to allocate.")
                return redirect("employees:it_support_timetable_page", tool="manual-allocation")
            class_id = slot["class_id"]
            allowed_pairs = {
                (subject.id, teacher.id) for subject, teacher in pairs_by_class.get(class_id, [])
            }
            if (subject_id, teacher_id) not in allowed_pairs:
                error(request, "Select a subject and teacher allocated to this class.")
                return redirect("employees:it_support_timetable_page", tool="manual-allocation")
            if GeneratedLearningLesson.objects.filter(
                academic_class_id=class_id,
                weekday=slot["weekday"],
                start_time=minutes_to_time(slot["start"]),
            ).exists():
                error(request, "This session is no longer free.")
                return redirect("employees:it_support_timetable_page", tool="manual-allocation")
            session = SimpleNamespace(
                id=None,
                weekday=slot["weekday"],
                start_time=minutes_to_time(slot["start"]),
                end_time=minutes_to_time(slot["end"]),
                academic_class_id=class_id,
            )
            others = GeneratedLearningLesson.objects.filter(
                teacher_id=teacher_id,
                weekday=slot["weekday"],
            ).select_related("academic_class", "teacher")
            conflict = next(
                (other for other in others if _learning_lesson_times_overlap(session, other)),
                None,
            )
            if conflict:
                error(
                    request,
                    f"{conflict.teacher.first_name} {conflict.teacher.last_name} is already teaching "
                    f"{conflict.academic_class.name} in this session.",
                )
                return redirect("employees:it_support_timetable_page", tool="manual-allocation")
            level_id = class_to_level.get(class_id)
            generation = _learning_generation_for_class(class_id, level_id)
            if not generation or level_id is None:
                error(request, "Generate a timetable for this class before allocating free sessions.")
                return redirect("employees:it_support_timetable_page", tool="manual-allocation")
            academic_class = get_object_or_404(AcademicClass, pk=class_id, status=AcademicClass.Status.ACTIVE)
            GeneratedLearningLesson.objects.create(
                generation=generation,
                academic_level_id=level_id,
                academic_class=academic_class,
                learning_area_id=subject_id,
                teacher_id=teacher_id,
                weekday=slot["weekday"],
                period_name=slot["period_name"],
                start_time=minutes_to_time(slot["start"]),
                end_time=minutes_to_time(slot["end"]),
            )
            success(request, f"Session allocated for {academic_class.name} only.")
            return redirect("employees:it_support_timetable_page", tool="manual-allocation")

        lesson = get_object_or_404(
            GeneratedLearningLesson,
            pk=request.POST.get("lesson_id"),
            academic_class_id__in=class_ids,
        )
        allowed_pairs = {
            (subject.id, teacher.id) for subject, teacher in pairs_by_class.get(lesson.academic_class_id, [])
        }
        allowed_pairs.add((lesson.learning_area_id, lesson.teacher_id))
        if (subject_id, teacher_id) not in allowed_pairs:
            error(request, "Select a subject and teacher allocated to this class.")
            return redirect("employees:it_support_timetable_page", tool="manual-allocation")
        others = GeneratedLearningLesson.objects.filter(
            teacher_id=teacher_id,
            weekday=lesson.weekday,
        ).exclude(pk=lesson.pk).select_related("academic_class", "teacher")
        conflict = next(
            (other for other in others if _learning_lesson_times_overlap(lesson, other)),
            None,
        )
        if conflict:
            error(
                request,
                f"{conflict.teacher.first_name} {conflict.teacher.last_name} is already teaching "
                f"{conflict.academic_class.name} in this session.",
            )
            return redirect("employees:it_support_timetable_page", tool="manual-allocation")
        lesson.learning_area_id = subject_id
        lesson.teacher_id = teacher_id
        lesson.save(update_fields=["learning_area", "teacher"])
        success(request, f"Session updated for {lesson.academic_class.name} only.")
        return redirect("employees:it_support_timetable_page", tool="manual-allocation")

    lesson_meta = {
        str(lesson.id): {
            "subject": lesson.learning_area.name,
            "subject_code": lesson.learning_area.code,
            "class_id": lesson.academic_class_id,
            "class_name": lesson.academic_class.name,
            "day_label": WEEKDAY_LABELS.get(lesson.weekday, lesson.weekday),
            "session": lesson.period_name,
            "time": f"{lesson.start_time.strftime('%H:%M')}–{lesson.end_time.strftime('%H:%M')}",
        }
        for lesson in lessons
    }
    return render(
        request,
        "employees/it_support_learning_manual_allocation.html",
        {
            "active_nav": "dashboard",
            "page": _it_support_timetable_page("timetable-generation"),
            "active_timetable_tool": "learning-manual-allocation",
            "manual_allocation": True,
            "timetable_groups": timetable_groups,
            "allocation_choices": _learning_allocation_options_by_lesson(lessons, pairs_by_class),
            "slot_allocation_choices": _learning_allocation_options_by_slot(
                timetable_groups, lessons, pairs_by_class
            ),
            "lesson_meta": lesson_meta,
            "slot_meta": slot_meta,
        },
    )


@login_required
def it_support_exam_page(request, tool):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = _it_support_exam_page(tool)
    if current is None:
        return redirect("employees:it_support_curriculum_section", section="exam-management")
    if current["slug"] == "allocate-supervisors":
        return exam_supervisor_allocation(request, current)
    if current["slug"] == "exam-timetable-generation":
        return exam_timetable_generation(request, current)
    if current["slug"] == "exam-records":
        return exam_records(request, current)
    return redirect("employees:it_support_curriculum_section", section="exam-management")


def _grouped_registered_exams():
    generations = list(
        GeneratedExamTimetable.objects.select_related("academic_year", "academic_term")
        .annotate(sitting_count=Count("sittings", distinct=True))
        .order_by("-academic_year__start_date", "academic_term__order", "-created_at")
    )
    active = _active_workflow_exam()
    for exam in generations:
        _annotate_exam_workflow_flags(exam)
    exam_groups = []
    for _year_id, exams in groupby(generations, key=lambda item: item.academic_year_id):
        exam_list = list(exams)
        exam_groups.append(
            {
                "year": exam_list[0].academic_year,
                "exams": exam_list,
            }
        )
    return exam_groups, len(generations), _current_exam_for_dashboard()


def exam_records(request, current):
    exam_groups, exam_count, current_exam = _grouped_registered_exams()
    return render(
        request,
        "employees/it_support_exam_records.html",
        {
            "active_nav": "dashboard",
            "page": current,
            "active_exam_tool": "exam-records",
            "exam_groups": exam_groups,
            "exam_count": exam_count,
            "current_exam": current_exam,
        },
    )


def _exam_record_manage_context(exam):
    academic_years = _registered_academic_years()
    terms_by_year = {
        str(year.id): [
            {
                "id": term.id,
                "name": term.name,
                "start": term.start_date.isoformat(),
                "end": term.end_date.isoformat(),
                "label": (
                    f"{term.name} ({term.start_date:%d %b %Y} – {term.end_date:%d %b %Y})"
                ),
            }
            for term in year.terms.all()
        ]
        for year in academic_years
    }
    return {
        "academic_years": academic_years,
        "academic_levels_for_exam": list(AcademicLevel.objects.order_by("order", "name")),
        "terms_by_year_json": json.dumps(terms_by_year),
        "exam_status_choices": GeneratedExamTimetable.Status.choices,
    }


def _exam_record_manage_redirect(request, exam_id, level_id=None):
    next_url = (request.POST.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    if level_id is not None:
        return redirect("employees:exam_record_level", exam_id=exam_id, level_id=level_id)
    return redirect("employees:exam_record_detail", exam_id=exam_id)


def _parse_exam_datetime(value):
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            if timezone.is_naive(parsed):
                return timezone.make_aware(parsed, timezone.get_current_timezone())
            return parsed
        except ValueError:
            continue
    return None


@login_required
@require_POST
def update_exam_record(request, exam_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    exam = get_object_or_404(GeneratedExamTimetable, pk=exam_id)
    exam_name = (request.POST.get("exam_name") or "").strip().upper()
    year_id = (request.POST.get("academic_year_id") or "").strip()
    term_id = (request.POST.get("academic_term_id") or "").strip()
    start_date = _parse_exam_date(request.POST.get("start_date"))
    end_date = _parse_exam_date(request.POST.get("end_date"))
    level_ids = []
    for raw_id in request.POST.getlist("academic_levels"):
        try:
            level_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    academic_years = {str(year.id): year for year in _registered_academic_years()}
    academic_year = academic_years.get(year_id)
    term = None
    if academic_year is not None and term_id:
        term = next(
            (item for item in academic_year.terms.all() if str(item.id) == term_id),
            None,
        )
    valid_level_ids = set(
        AcademicLevel.objects.filter(pk__in=level_ids).values_list("id", flat=True)
    )
    level_ids = [level_id for level_id in level_ids if level_id in valid_level_ids]

    if not exam_name:
        error(request, "Enter a name for this assessment.")
    elif academic_year is None:
        error(request, "Select a registered academic year.")
    elif term is None:
        error(request, "Select an academic term from the selected academic year.")
    elif start_date is None:
        error(request, "Select when the assessment starts.")
    elif end_date is None:
        error(request, "Select when the assessment ends.")
    elif end_date < start_date:
        error(request, "Assessment end date must be on or after the start date.")
    elif start_date < term.start_date or end_date > term.end_date:
        error(
            request,
            f"Assessment dates must fall inside {term.name} "
            f"({term.start_date:%d %b %Y} to {term.end_date:%d %b %Y}).",
        )
    elif not level_ids:
        error(request, "Select at least one academic level.")
    else:
        with transaction.atomic():
            exam.name = exam_name
            exam.academic_year = academic_year
            exam.academic_term = term
            exam.start_date = start_date
            exam.end_date = end_date
            exam.save()
            exam.academic_levels.set(level_ids)
        success(request, f"{exam.display_name} was updated.")
    level_id = request.POST.get("level_id") or None
    if level_id is not None and str(level_id).isdigit():
        level_id = int(level_id)
    else:
        level_id = None
    return _exam_record_manage_redirect(request, exam_id, level_id=level_id)


@login_required
@require_POST
def update_exam_record_status(request, exam_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    exam = get_object_or_404(GeneratedExamTimetable, pk=exam_id)
    status = (request.POST.get("status") or "").strip()
    valid_statuses = {choice for choice, _label in GeneratedExamTimetable.Status.choices}
    level_id = request.POST.get("level_id") or None
    if level_id is not None and str(level_id).isdigit():
        level_id = int(level_id)
    else:
        level_id = None
    if status not in valid_statuses:
        error(request, "Select a valid assessment status.")
        return _exam_record_manage_redirect(request, exam_id, level_id=level_id)

    if exam.status == GeneratedExamTimetable.Status.PUBLISHED:
        error(request, "Published exams cannot be changed.")
        return _exam_record_manage_redirect(request, exam_id, level_id=level_id)

    active = _active_workflow_exam()
    if exam.status == GeneratedExamTimetable.Status.SCHEDULED:
        if status not in GeneratedExamTimetable.ACTIVE_WORKFLOW_STATUSES:
            error(request, "Scheduled exams can only be started by setting them to In session.")
            return _exam_record_manage_redirect(request, exam_id, level_id=level_id)
        if active is not None:
            error(
                request,
                f"Only one exam can be current at a time. Finish {active.display_name} before starting another.",
            )
            return _exam_record_manage_redirect(request, exam_id, level_id=level_id)
    elif exam.status not in GeneratedExamTimetable.ACTIVE_WORKFLOW_STATUSES:
        error(request, "You can only change status for the current exam.")
        return _exam_record_manage_redirect(request, exam_id, level_id=level_id)

    with transaction.atomic():
        if status in GeneratedExamTimetable.ACTIVE_WORKFLOW_STATUSES:
            _demote_other_active_exams(exam)
        exam.status = status
        exam.save(update_fields=["status"])
    label = dict(GeneratedExamTimetable.Status.choices).get(status, status)
    success(request, f"{exam.display_name} status set to {label.lower()}.")
    return _exam_record_manage_redirect(request, exam_id, level_id=level_id)


@login_required
@require_POST
def set_current_exam_record(request, exam_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    exam = get_object_or_404(GeneratedExamTimetable, pk=exam_id)
    records_url = reverse("employees:it_support_exam_page", kwargs={"tool": "exam-records"})
    next_url = (request.POST.get("next") or "").strip()
    redirect_target = records_url
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        redirect_target = next_url

    if exam.status == GeneratedExamTimetable.Status.PUBLISHED:
        error(request, "Published assessments cannot be set as current.")
        return redirect(redirect_target)

    is_current = request.POST.get("is_current") == "1"

    if not is_current:
        if exam.status in GeneratedExamTimetable.ACTIVE_WORKFLOW_STATUSES:
            exam.status = GeneratedExamTimetable.Status.SCHEDULED
            exam.save(update_fields=["status"])
            success(request, f"{exam.display_name} is no longer the current exam.")
        return redirect(redirect_target)

    if _is_current_exam(exam):
        return redirect(redirect_target)

    with transaction.atomic():
        _demote_other_active_exams(exam)
        if exam.status == GeneratedExamTimetable.Status.SCHEDULED:
            exam.status = GeneratedExamTimetable.Status.IN_SESSION
            exam.save(update_fields=["status"])
    success(request, f"{exam.display_name} is now the current exam.")
    return redirect(redirect_target)


@login_required
@require_POST
def update_exam_record_deadline(request, exam_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    exam = get_object_or_404(GeneratedExamTimetable, pk=exam_id)
    level_id = request.POST.get("level_id") or None
    if level_id is not None and str(level_id).isdigit():
        level_id = int(level_id)
    else:
        level_id = None
    if request.POST.get("clear_deadline") == "1":
        exam.deadline = None
        exam.save(update_fields=["deadline"])
        success(request, f"Deadline cleared for {exam.display_name}.")
        return _exam_record_manage_redirect(request, exam_id, level_id=level_id)
    deadline = _parse_exam_datetime(request.POST.get("deadline"))
    if deadline is None:
        error(request, "Select a valid deadline date and time.")
    else:
        exam.deadline = deadline
        exam.save(update_fields=["deadline"])
        success(request, f"Deadline updated for {exam.display_name}.")
    return _exam_record_manage_redirect(request, exam_id, level_id=level_id)


@login_required
@require_POST
def delete_exam_record(request, exam_id):
    denied = _require_it_support(request)
    if denied:
        return denied
    exam = get_object_or_404(GeneratedExamTimetable, pk=exam_id)
    name = exam.display_name
    exam.delete()
    success(request, f"{name} was deleted.")
    return redirect("employees:it_support_exam_page", tool="exam-records")


def _exam_record_title(generation):
    return generation.display_name


def _student_level_choice(level):
    name = (level.name or "").strip()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).upper().strip("_")
    if slug in Student.AcademicLevel.values:
        return slug
    for value, label in Student.AcademicLevel.choices:
        if label.casefold() == name.casefold():
            return value
        if value.replace("_", " ").casefold() == name.casefold():
            return value
    return ""


def _students_in_academic_level(level, academic_class=None, sort=STUDENT_SORT_NAME):
    choice = _student_level_choice(level)
    if not choice:
        return Student.objects.none()
    sort_mode = sort if sort in STUDENT_SORT_CHOICES else STUDENT_SORT_NAME
    students = Student.objects.select_related("parent_guardian").filter(academic_level=choice).order_by(
        *_student_sort_order_by(sort_mode, include_class_group=True),
    )
    if academic_class is None:
        return students
    class_values = _class_group_values(academic_class)
    query = Q()
    for value in class_values:
        query |= Q(class_group__iexact=value)
    if not query:
        return students.none()
    return students.filter(query)


def _exam_record_subjects(level, academic_class=None):
    return [item["area"] for item in _build_exam_subjects(level)]


def _level_combined_exam_subjects(level):
    return list(
        CombinedExamSubject.objects.filter(academic_level=level)
        .prefetch_related(
            Prefetch(
                "components",
                queryset=CombinedExamSubjectComponent.objects.select_related(
                    "subject_setting__learning_area"
                ),
            )
        )
    )


def _exam_record_display_columns(level):
    built_subjects = _build_exam_subjects(level)
    combined_area_ids = set()
    combined_entries = []
    for combined in _level_combined_exam_subjects(level):
        components = list(combined.components.all())
        component_areas = [component.subject_setting.learning_area for component in components]
        component_ids = [area.id for area in component_areas]
        combined_area_ids.update(component_ids)
        order_indexes = [
            index
            for index, item in enumerate(built_subjects)
            if item["area"].id in component_ids
        ]
        combined_entries.append(
            {
                "kind": "combined",
                "combined": combined,
                "code": combined.code,
                "name": combined.name,
                "component_codes": combined.component_codes,
                "component_ids": component_ids,
                "sort_key": min(order_indexes) if order_indexes else len(built_subjects),
            }
        )

    columns = []
    for index, item in enumerate(built_subjects):
        area = item["area"]
        if area.id in combined_area_ids:
            continue
        columns.append(
            {
                "kind": "subject",
                "subject": area,
                "code": area.code,
                "name": area.name,
                "sort_key": index,
            }
        )
    columns.extend(combined_entries)
    columns.sort(key=lambda column: column["sort_key"])
    return columns


def _combined_exam_percent(marks_lookup, student_id, component_ids, out_of_by_subject):
    total_raw = 0
    total_out_of = 0
    for component_id in component_ids:
        entry = marks_lookup.get((student_id, component_id))
        raw = _exam_mark_entry_raw(entry)
        if raw in (None, ""):
            return None
        current_out_of = out_of_by_subject.get(component_id)
        saved_out_of = _exam_mark_entry_out_of(entry, None) if isinstance(entry, dict) else None
        display_out_of = saved_out_of if saved_out_of is not None else current_out_of
        if not display_out_of:
            return None
        total_raw += int(raw)
        total_out_of += int(display_out_of)
    return _marks_as_percent(total_raw, total_out_of)


def _attach_exam_record_display_cells(students, display_columns, marks_lookup, out_of_by_subject):
    for student in students:
        student.mark_cells = []
        for column in display_columns:
            if column["kind"] == "combined":
                percent = _combined_exam_percent(
                    marks_lookup,
                    student.id,
                    column["component_ids"],
                    out_of_by_subject,
                )
                student.mark_cells.append(
                    {
                        "kind": "combined",
                        "column": column,
                        "code": column["code"],
                        "name": column["name"],
                        "component_codes": column["component_codes"],
                        "percent": percent,
                        "readonly": True,
                    }
                )
                continue

            subject = column["subject"]
            current_out_of = out_of_by_subject.get(subject.id, subject.total_marks)
            entry = marks_lookup.get((student.id, subject.id))
            stored = _exam_mark_entry_raw(entry)
            saved_out_of = _exam_mark_entry_out_of(entry, None) if isinstance(entry, dict) else None
            if stored not in (None, "") and saved_out_of is not None:
                display_out_of = saved_out_of
            else:
                display_out_of = current_out_of
            settings_changed = (
                stored not in (None, "")
                and saved_out_of is not None
                and int(saved_out_of) != int(current_out_of)
            )
            student.mark_cells.append(
                {
                    "kind": "subject",
                    "column": column,
                    "subject": subject,
                    "code": column["code"],
                    "name": column["name"],
                    "out_of": display_out_of,
                    "current_out_of": current_out_of,
                    "saved_out_of": saved_out_of,
                    "settings_changed": settings_changed,
                    "percent": _marks_as_percent(stored, display_out_of),
                    "field_name": f"mark_{student.id}_{subject.id}",
                    "readonly": False,
                }
            )


def _exam_record_out_of(level, subjects):
    built = {item["area"].id: item["out_of_marks"] for item in _build_exam_subjects(level)}
    return {subject.id: built.get(subject.id, subject.total_marks) for subject in subjects}


def _marks_as_percent(score, out_of):
    if score in (None, "") or not out_of:
        return None
    try:
        value = int(score)
    except (TypeError, ValueError):
        return None
    return round((value * 100) / out_of)


def _exam_mark_entry_raw(entry):
    if entry is None:
        return None
    if isinstance(entry, dict):
        return entry.get("marks")
    return entry


def _exam_mark_entry_out_of(entry, fallback):
    if isinstance(entry, dict):
        saved = entry.get("out_of_marks")
        if saved not in (None, ""):
            try:
                return int(saved)
            except (TypeError, ValueError):
                pass
    return fallback


def _exam_marks_out_of_settings_changed(marks_lookup, out_of_by_subject):
    """True when any saved mark's snapshotted out-of differs from current settings."""
    for key, entry in marks_lookup.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("marks") in (None, ""):
            continue
        saved = entry.get("out_of_marks")
        if saved in (None, ""):
            continue
        subject_id = key[1]
        current = out_of_by_subject.get(subject_id)
        if current is None:
            continue
        try:
            if int(saved) != int(current):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _prefetched_m2m_items(instance, field_name):
    cache = getattr(instance, "_prefetched_objects_cache", None)
    if cache is not None and field_name in cache:
        return list(cache[field_name])
    return None


def _exam_has_academic_levels(exam_item):
    levels = _prefetched_m2m_items(exam_item, "academic_levels")
    if levels is not None:
        return bool(levels)
    return exam_item.academic_levels.exists()


def _exam_includes_academic_level(exam_item, level_id):
    levels = _prefetched_m2m_items(exam_item, "academic_levels")
    if levels is not None:
        return any(level.id == level_id for level in levels)
    return exam_item.academic_levels.filter(pk=level_id).exists()


def _exam_record_mark_lookup(generation, students, subjects):
    if not students or not subjects:
        return {}
    return _exam_record_marks_lookup_multi([generation], students, subjects).get(generation.id, {})


def _exam_record_marks_lookup_multi(generations, students, subjects):
    if not generations or not students or not subjects:
        return {}
    student_ids = [student.id for student in students]
    subject_ids = [subject.id for subject in subjects]
    generation_ids = [generation.id for generation in generations]
    lookups = defaultdict(dict)
    for item in ExamMark.objects.filter(
        generation_id__in=generation_ids,
        student_id__in=student_ids,
        learning_area_id__in=subject_ids,
    ):
        lookups[item.generation_id][(item.student_id, item.learning_area_id)] = {
            "marks": item.marks,
            "out_of_marks": item.out_of_marks,
        }
    return lookups


def _percent_to_raw_marks(percent, out_of):
    return round((percent * out_of) / 100)


def _exam_record_subject_means(students, subjects):
    means = []
    for subject_index, subject in enumerate(subjects):
        raw_values = []
        out_of = None
        for student in students:
            cell = student.mark_cells[subject_index]
            out_of = cell["out_of"]
            raw = cell.get("raw")
            if raw in (None, ""):
                continue
            try:
                raw_values.append(int(raw))
            except (TypeError, ValueError):
                continue
        if raw_values:
            raw_mean = round(sum(raw_values) / len(raw_values))
            percent_mean = _marks_as_percent(raw_mean, out_of)
        else:
            raw_mean = None
            percent_mean = None
        means.append(
            {
                "subject": subject,
                "raw_mean": raw_mean,
                "percent_mean": percent_mean,
                "out_of": out_of,
                "count": len(raw_values),
            }
        )
    return means


def _exam_record_display_column_means(students, display_columns):
    means = []
    for col_index, column in enumerate(display_columns):
        values = []
        for student in students:
            if col_index >= len(student.mark_cells):
                continue
            percent = student.mark_cells[col_index].get("percent")
            if percent in (None, ""):
                continue
            try:
                values.append(int(percent))
            except (TypeError, ValueError):
                continue
        percent_mean = round(sum(values) / len(values)) if values else None
        means.append(
            {
                "column": column,
                "code": column["code"],
                "percent_mean": percent_mean,
            }
        )
    return means


def _attach_exam_mark_cells(students, subjects, marks_lookup, out_of_by_subject, values_are_percent=False):
    for student in students:
        student.mark_cells = []
        for subject in subjects:
            current_out_of = out_of_by_subject.get(subject.id, subject.total_marks)
            entry = marks_lookup.get((student.id, subject.id))
            if values_are_percent:
                if entry in (None, ""):
                    percent = None
                    stored = None
                else:
                    try:
                        percent = int(entry) if not isinstance(entry, dict) else int(
                            _exam_mark_entry_raw(entry)
                        )
                    except (TypeError, ValueError):
                        percent = entry if not isinstance(entry, dict) else _exam_mark_entry_raw(entry)
                    stored = None
                display_out_of = current_out_of
                saved_out_of = None
                settings_changed = False
            else:
                stored = _exam_mark_entry_raw(entry)
                saved_out_of = _exam_mark_entry_out_of(entry, None) if isinstance(entry, dict) else None
                if stored not in (None, "") and saved_out_of is not None:
                    display_out_of = saved_out_of
                else:
                    display_out_of = current_out_of
                settings_changed = (
                    stored not in (None, "")
                    and saved_out_of is not None
                    and int(saved_out_of) != int(current_out_of)
                )
                percent = _marks_as_percent(stored, display_out_of)
            student.mark_cells.append(
                {
                    "subject": subject,
                    "out_of": display_out_of,
                    "current_out_of": current_out_of,
                    "saved_out_of": saved_out_of,
                    "settings_changed": settings_changed,
                    "raw": None if values_are_percent else stored,
                    "percent": percent,
                    "field_name": f"mark_{student.id}_{subject.id}",
                }
            )


def _save_exam_record_marks(
    generation, students, subjects, out_of_by_subject, post_data, input_is_percent=True
):
    to_upsert = []
    to_delete = []
    for student in students:
        for subject in subjects:
            raw = (post_data.get(f"mark_{student.id}_{subject.id}") or "").strip()
            if raw == "":
                to_delete.append((student.id, subject.id))
                continue
            marks = int(raw)
            limit = out_of_by_subject.get(subject.id, subject.total_marks)
            if input_is_percent:
                if marks < 0 or marks > 100:
                    raise ValidationError("Marks must be a whole number out of 100%.")
                stored = _percent_to_raw_marks(marks, limit)
            else:
                if marks < 0 or marks > limit:
                    raise ValidationError(f"Marks must be a whole number out of {limit}.")
                stored = marks
            to_upsert.append((student.id, subject.id, stored, limit))
    with transaction.atomic():
        if to_delete:
            query = Q()
            for student_id, subject_id in to_delete:
                query |= Q(student_id=student_id, learning_area_id=subject_id)
            ExamMark.objects.filter(generation=generation).filter(query).delete()
        bulk_upsert_by_keys(
            ExamMark,
            scope_filter={"generation_id": generation.id},
            create_defaults={"generation_id": generation.id},
            rows=[
                {
                    "student_id": student_id,
                    "learning_area_id": subject_id,
                    "marks": marks,
                    "out_of_marks": out_of,
                }
                for student_id, subject_id, marks, out_of in to_upsert
            ],
            key_fields=("student_id", "learning_area_id"),
            update_fields=("marks", "out_of_marks"),
        )


@login_required
@require_http_methods(["GET", "POST"])
def exam_record_detail(request, exam_id, level_id=None):
    denied = _require_it_support(request)
    if denied:
        return denied
    generation = get_object_or_404(
        GeneratedExamTimetable.objects.select_related("academic_year", "academic_term")
        .prefetch_related("academic_levels")
        .annotate(
            sitting_count=Count("sittings", distinct=True)
        ),
        pk=exam_id,
    )
    if request.method == "POST" and level_id is None:
        return redirect("employees:exam_record_detail", exam_id=exam_id)
    academic_levels = list(generation.academic_levels.order_by("order", "name"))
    if not academic_levels:
        academic_levels = list(AcademicLevel.objects.order_by("order", "name"))
    selected_level = None
    selected_class = None
    level_classes = []
    students = []
    subjects = []
    display_columns = []
    subject_means = []
    out_of_by_subject = {}
    out_of_settings_changed = False
    if level_id is not None:
        selected_level = get_object_or_404(
            AcademicLevel.objects.prefetch_related(
                Prefetch(
                    "learning_areas",
                    queryset=LearningArea.objects.filter(status=LearningArea.Status.ACTIVE).order_by(
                        "display_order", "name"
                    ),
                ),
                Prefetch("exam_subject_settings", queryset=ExamSubjectSetting.objects.select_related("learning_area")),
            ),
            pk=level_id,
        )
        level_classes = list(
            AcademicClass.objects.filter(academic_level=selected_level).order_by("order", "name")
        )
        class_id = request.POST.get("class_id") if request.method == "POST" else request.GET.get("class_id")
        class_id = class_id or ""
        if class_id.isdigit():
            selected_class = next(
                (item for item in level_classes if item.id == int(class_id)),
                None,
            )
        students = list(_students_in_academic_level(selected_level, selected_class))
        subjects = _exam_record_subjects(selected_level, selected_class)
        display_columns = _exam_record_display_columns(selected_level)
        out_of_by_subject = _exam_record_out_of(selected_level, subjects)
        for subject in subjects:
            subject.exam_out_of = out_of_by_subject.get(subject.id, subject.total_marks)
        if request.method == "POST":
            try:
                _save_exam_record_marks(
                    generation,
                    students,
                    subjects,
                    out_of_by_subject,
                    request.POST,
                )
            except (TypeError, ValueError, ValidationError):
                error(request, "Enter whole numbers from 0 to 100 for each subject.")
                marks_lookup = _exam_record_mark_lookup(generation, students, subjects)
                for student in students:
                    for subject in subjects:
                        raw_post = (request.POST.get(f"mark_{student.id}_{subject.id}") or "").strip()
                        if raw_post == "":
                            continue
                        try:
                            percent = int(raw_post)
                        except (TypeError, ValueError):
                            continue
                        out_of = out_of_by_subject.get(subject.id, subject.total_marks)
                        marks_lookup[(student.id, subject.id)] = {
                            "marks": _percent_to_raw_marks(percent, out_of),
                            "out_of_marks": out_of,
                        }
                _attach_exam_record_display_cells(
                    students,
                    display_columns,
                    marks_lookup,
                    out_of_by_subject,
                )
                subject_means = _exam_record_display_column_means(students, display_columns)
            else:
                success(request, "Student marks were saved.")
                redirect_url = reverse(
                    "employees:exam_record_level",
                    kwargs={"exam_id": generation.id, "level_id": selected_level.id},
                )
                if selected_class:
                    redirect_url = f"{redirect_url}?class_id={selected_class.id}"
                return redirect(redirect_url)
        else:
            marks_lookup = _exam_record_mark_lookup(generation, students, subjects)
            out_of_settings_changed = _exam_marks_out_of_settings_changed(
                marks_lookup, out_of_by_subject
            )
            _attach_exam_record_display_cells(
                students,
                display_columns,
                marks_lookup,
                out_of_by_subject,
            )
            subject_means = _exam_record_display_column_means(students, display_columns)
    else:
        display_columns = []
    return render(
        request,
        "employees/it_support_exam_record_detail.html",
        {
            "active_nav": "dashboard",
            "page": _it_support_exam_page("exam-records"),
            "exam": generation,
            "exam_title": _exam_record_title(generation),
            "academic_levels": academic_levels,
            "selected_level": selected_level,
            "selected_class": selected_class,
            "level_classes": level_classes,
            "students": students,
            "subjects": subjects,
            "display_columns": display_columns,
            "subject_means": subject_means,
            "out_of_settings_changed": out_of_settings_changed,
            "manage_next_url": request.get_full_path(),
            "can_change_exam_status": _can_change_exam_status(generation),
            "is_current_exam": _is_current_exam(generation),
            "can_toggle_current": generation.status != GeneratedExamTimetable.Status.PUBLISHED,
            **_exam_record_manage_context(generation),
        },
    )


def _exam_supervisor_allocation_levels():
    active_classes = AcademicClass.objects.filter(status=AcademicClass.Status.ACTIVE).order_by("order", "name")
    active_subjects = LearningArea.objects.filter(status=LearningArea.Status.ACTIVE).order_by(
        "display_order", "name"
    )
    levels = list(
        AcademicLevel.objects.filter(status=AcademicLevel.Status.ACTIVE)
        .prefetch_related(
            Prefetch("classes", queryset=active_classes),
            Prefetch("learning_areas", queryset=active_subjects),
        )
        .order_by("order", "name")
    )
    class_ids = [academic_class.id for level in levels for academic_class in level.classes.all()]
    supervisors = {
        (item.academic_class_id, item.learning_area_id): item.supervisor
        for item in ExamSupervisorAllocation.objects.filter(academic_class_id__in=class_ids).select_related(
            "supervisor"
        )
    }
    subject_teachers = {
        (item.academic_class_id, item.learning_area_id): item.teacher
        for item in ClassSubjectAllocation.objects.filter(academic_class_id__in=class_ids).select_related(
            "teacher"
        )
    }
    for level in levels:
        classes = list(level.classes.all())
        subjects = list(level.learning_areas.all())
        rows = []
        for subject in subjects:
            teachers = []
            seen_teacher_ids = set()
            supervisor_ids = set()
            supervisor = None
            for academic_class in classes:
                teacher = subject_teachers.get((academic_class.id, subject.id))
                if teacher and teacher.id not in seen_teacher_ids:
                    teachers.append(teacher)
                    seen_teacher_ids.add(teacher.id)
                class_supervisor = supervisors.get((academic_class.id, subject.id))
                if class_supervisor:
                    supervisor_ids.add(class_supervisor.id)
                    supervisor = class_supervisor
            rows.append(
                {
                    "subject": subject,
                    "teachers": teachers,
                    "supervisor": supervisor if len(supervisor_ids) == 1 else None,
                    "supervisor_conflict": len(supervisor_ids) > 1,
                }
            )
        level.allocation_classes = classes
        level.allocation_rows = rows
    return levels


@login_required
@require_http_methods(["GET", "POST"])
def exam_supervisor_allocation(request, page=None):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = page or _it_support_exam_page("allocate-supervisors")
    teachers = list(_approved_teachers())

    if request.method == "POST":
        level = get_object_or_404(
            AcademicLevel,
            pk=request.POST.get("level_id"),
            status=AcademicLevel.Status.ACTIVE,
        )
        classes = list(level.classes.filter(status=AcademicClass.Status.ACTIVE).order_by("order", "name"))
        subjects = list(level.learning_areas.filter(status=LearningArea.Status.ACTIVE).order_by("display_order", "name"))
        if not teachers:
            error(request, "No approved teachers are available to supervise assessments.")
        elif not classes:
            error(request, "Register classes for this level before allocating supervisors.")
        elif not subjects:
            error(request, "Link subjects to this academic level before allocating supervisors.")
        else:
            class_ids = [academic_class.id for academic_class in classes]
            subject_teacher_ids = {}
            for item in ClassSubjectAllocation.objects.filter(academic_class_id__in=class_ids):
                subject_teacher_ids.setdefault(item.learning_area_id, set()).add(item.teacher_id)
            assignments = shuffle_level_supervisors(subjects, subject_teacher_ids, teachers)
            with transaction.atomic():
                allocation_rows = []
                for subject in subjects:
                    supervisor = assignments.get(subject.id)
                    if supervisor is None:
                        ExamSupervisorAllocation.objects.filter(
                            academic_class_id__in=class_ids,
                            learning_area=subject,
                        ).delete()
                        continue
                    for academic_class in classes:
                        allocation_rows.append(
                            {
                                "academic_class_id": academic_class.id,
                                "learning_area_id": subject.id,
                                "supervisor_id": supervisor.id,
                            }
                        )
                if allocation_rows:
                    bulk_upsert_by_keys(
                        ExamSupervisorAllocation,
                        scope_filter={"academic_class_id__in": class_ids},
                        rows=allocation_rows,
                        key_fields=("academic_class_id", "learning_area_id"),
                        update_fields=("supervisor_id",),
                    )
                ExamSupervisorAllocation.objects.filter(
                    academic_class_id__in=class_ids,
                ).exclude(learning_area_id__in=[subject.id for subject in subjects]).delete()
            success(
                request,
                f"Supervisors shuffled for {level.name}. Classes in this level sit as one group.",
            )
        return redirect("employees:it_support_exam_page", tool="allocate-supervisors")

    levels = _exam_supervisor_allocation_levels()
    return render(
        request,
        "employees/it_support_exam_supervisor_allocation.html",
        {
            "active_nav": "dashboard",
            "page": current,
            "active_exam_tool": "allocate-supervisors",
            "teachers": teachers,
            "level_groups": group_academic_levels_by_category(levels),
        },
    )


def _exam_timetable_generation_levels():
    supervisor_ids = _active_teacher_ids()
    active_classes = AcademicClass.objects.filter(status=AcademicClass.Status.ACTIVE).order_by("order", "name")
    active_subjects = LearningArea.objects.filter(status=LearningArea.Status.ACTIVE).order_by(
        "display_order", "name"
    )
    levels = list(
        AcademicLevel.objects.filter(status=AcademicLevel.Status.ACTIVE)
        .prefetch_related(
            Prefetch("classes", queryset=active_classes),
            Prefetch("learning_areas", queryset=active_subjects),
            Prefetch(
                "exam_schedule_profiles",
                queryset=ExamScheduleProfile.objects.prefetch_related("activities").order_by(
                    "category", "name", "id"
                ),
            ),
        )
        .order_by("order", "name")
    )
    class_ids = [academic_class.id for level in levels for academic_class in level.classes.all()]
    allocations = {
        (item.academic_class_id, item.learning_area_id): item.supervisor_id
        for item in ExamSupervisorAllocation.objects.filter(
            academic_class_id__in=class_ids,
            supervisor_id__in=supervisor_ids,
        )
    }
    for level in levels:
        classes = list(level.classes.all())
        subjects = list(level.learning_areas.all())
        missing = 0
        for academic_class in classes:
            for subject in subjects:
                if allocations.get((academic_class.id, subject.id)) not in supervisor_ids:
                    missing += 1
        level.generation_classes = classes
        level.generation_subjects = subjects
        level.missing_allocations = missing
        profile = resolve_exam_schedule_profile(level)
        slots = exam_slots_from_profile(profile)
        level.schedule_profile = profile
        level.schedule_slots = slots
        level.schedule_days = sorted({slot["weekday"] for slot in slots}, key=lambda day: 0 if day == "EXM" else DAY_ORDER.index(day) if day in DAY_ORDER else 99)
        level.schedule_periods = len({(slot["start"], slot["end"], slot["period_name"]) for slot in slots})
        allocations_ready = bool(classes and subjects)
        settings_ready = bool(profile and slots)
        level.is_viable = allocations_ready and settings_ready
        if not classes:
            level.viability_reason = "Register at least one active class."
        elif not subjects:
            level.viability_reason = "Link at least one active subject."
        elif not profile:
            level.viability_reason = "Add this level to an assessment timetable settings profile."
        elif not slots:
            level.viability_reason = "Complete assessment timetable settings so assessment sessions can be generated."
        else:
            profile_info = (
                f"{profile.name}: {level.schedule_periods} session"
                f"{'' if level.schedule_periods == 1 else 's'} from the assessment profile."
            )
            if missing:
                level.viability_reason = (
                    f"{profile_info} {missing} class subject{'' if missing == 1 else 's'} "
                    f"without a supervisor — supervisors can be assigned later."
                )
            else:
                level.viability_reason = profile_info
    return levels, allocations, supervisor_ids


def _generate_exams_for_levels(generation, levels, allocations, supervisor_ids, exam_dates_by_level=None):
    class_plans = build_exam_class_plans(
        levels,
        allocations,
        supervisor_ids,
        exam_dates_by_level=exam_dates_by_level,
    )
    placements, total_slots = generate_exam_timetable_plan(class_plans)
    created = persist_exam_timetable_plan(generation, placements)
    return created, total_slots


def _generated_exam_timetables(levels, generation=None):
    class_ids = [
        academic_class.id
        for level in levels
        for academic_class in getattr(level, "generation_classes", [])
    ]
    sittings_query = GeneratedExamSitting.objects.filter(academic_class_id__in=class_ids)
    if generation is not None:
        sittings_query = sittings_query.filter(generation=generation)
    sittings = list(
        sittings_query.select_related(
            "academic_class",
            "academic_level",
            "learning_area",
            "supervisor",
            "generation",
            "generation__academic_year",
            "generation__academic_term",
        )
        .order_by("academic_level__order", "academic_class__order", "exam_date", "weekday", "start_time")
    )
    colliding_ids = _colliding_exam_sitting_ids(sittings)
    by_class = {}
    for sitting in sittings:
        by_class.setdefault(sitting.academic_class_id, []).append(sitting)

    groups = []
    for level in levels:
        class_grids = []
        for academic_class in getattr(level, "generation_classes", []):
            class_sittings = by_class.get(academic_class.id, [])
            if not class_sittings:
                continue
            slots = list(getattr(level, "schedule_slots", []) or [])
            dated_sittings = [item for item in class_sittings if item.exam_date]
            if dated_sittings:
                days = []
                seen_days = set()
                periods = []
                seen_periods = set()
                for sitting in dated_sittings:
                    day_key = sitting.exam_date.isoformat()
                    if day_key not in seen_days:
                        seen_days.add(day_key)
                        days.append(
                            {
                                "code": day_key,
                                "label": sitting.exam_date.strftime("%A %d %b %Y"),
                            }
                        )
                    period_key = (to_minutes(sitting.start_time), to_minutes(sitting.end_time), sitting.period_name)
                    if period_key not in seen_periods:
                        seen_periods.add(period_key)
                        periods.append(
                            {
                                "name": sitting.period_name,
                                "start": to_minutes(sitting.start_time),
                                "end": to_minutes(sitting.end_time),
                                "start_label": sitting.start_time.strftime("%H:%M"),
                                "end_label": sitting.end_time.strftime("%H:%M"),
                            }
                        )
                periods.sort(key=lambda item: (item["start"], item["end"], item["name"]))
                lookup = {
                    (sitting.exam_date.isoformat(), to_minutes(sitting.start_time)): sitting
                    for sitting in dated_sittings
                }
                rows = []
                for day in days:
                    cells = []
                    for period in periods:
                        sitting = lookup.get((day["code"], period["start"]))
                        cells.append(_exam_timetable_cell(sitting, colliding_ids))
                    rows.append({"day_code": day["code"], "day_label": day["label"], "cells": cells})
            elif slots:
                days = []
                seen_days = set()
                periods = []
                seen_periods = set()
                for slot in slots:
                    if slot["weekday"] not in seen_days:
                        seen_days.add(slot["weekday"])
                        days.append(slot["weekday"])
                    period_key = (slot["start"], slot["end"], slot["period_name"])
                    if period_key not in seen_periods:
                        seen_periods.add(period_key)
                        periods.append(
                            {
                                "name": slot["period_name"],
                                "start": slot["start"],
                                "end": slot["end"],
                                "start_label": f"{slot['start'] // 60:02d}:{slot['start'] % 60:02d}",
                                "end_label": f"{slot['end'] // 60:02d}:{slot['end'] % 60:02d}",
                            }
                        )
                lookup = {
                    (sitting.weekday, to_minutes(sitting.start_time)): sitting
                    for sitting in class_sittings
                }
                rows = []
                for day in days:
                    cells = []
                    for period in periods:
                        sitting = lookup.get((day, period["start"]))
                        cells.append(_exam_timetable_cell(sitting, colliding_ids))
                    rows.append(
                        {
                            "day_code": day,
                            "day_label": WEEKDAY_LABELS.get(day, day),
                            "cells": cells,
                        }
                    )
            else:
                days = [day for day in DAY_ORDER if any(item.weekday == day for item in class_sittings)]
                if any(item.weekday == "EXM" for item in class_sittings) and "EXM" not in days:
                    days = ["EXM"] + days
                periods = []
                seen_periods = set()
                for sitting in sorted(class_sittings, key=lambda item: item.start_time):
                    start = to_minutes(sitting.start_time)
                    end = to_minutes(sitting.end_time)
                    period_key = (start, end, sitting.period_name)
                    if period_key in seen_periods:
                        continue
                    seen_periods.add(period_key)
                    periods.append(
                        {
                            "name": sitting.period_name,
                            "start": start,
                            "end": end,
                            "start_label": sitting.start_time.strftime("%H:%M"),
                            "end_label": sitting.end_time.strftime("%H:%M"),
                        }
                    )
                lookup = {
                    (sitting.weekday, to_minutes(sitting.start_time)): sitting
                    for sitting in class_sittings
                }
                rows = []
                for day in days:
                    cells = []
                    for period in periods:
                        sitting = lookup.get((day, period["start"]))
                        cells.append(_exam_timetable_cell(sitting, colliding_ids))
                    rows.append(
                        {
                            "day_code": day,
                            "day_label": WEEKDAY_LABELS.get(day, day),
                            "cells": cells,
                        }
                    )
            generation = class_sittings[0].generation
            class_grids.append(
                {
                    "academic_class": academic_class,
                    "sitting_count": len(class_sittings),
                    "exam_name": generation.name if generation else "",
                    "academic_year": generation.academic_year if generation else None,
                    "academic_term": generation.academic_term if generation else None,
                    "start_date": generation.start_date if generation else None,
                    "end_date": generation.end_date if generation else None,
                    "periods": periods,
                    "rows": rows,
                }
            )
        if class_grids:
            groups.append({"level": level, "classes": class_grids})
    return groups


def _exam_timetable_cell(sitting, colliding_ids):
    return {
        "sitting": sitting,
        "is_blank": sitting is None,
        "hide_supervisor": bool(
            sitting and (sitting.id in colliding_ids or sitting.supervisor_id is None)
        ),
    }


def _exam_sitting_times_overlap(left, right):
    if not left or not right:
        return False
    if left.exam_date != right.exam_date:
        return False
    return to_minutes(left.start_time) < to_minutes(right.end_time) and to_minutes(right.start_time) < to_minutes(
        left.end_time
    )


def _colliding_exam_sitting_ids(sittings):
    colliding = set()
    items = list(sittings)
    for index, current in enumerate(items):
        for other in items[index + 1 :]:
            if current.supervisor_id is None or other.supervisor_id is None:
                continue
            if current.supervisor_id != other.supervisor_id:
                continue
            if _exam_sitting_times_overlap(current, other):
                colliding.add(current.id)
                colliding.add(other.id)
    return colliding


def _exam_supervisor_options_by_sitting(sittings, teachers):
    choices = {}
    for sitting in sittings:
        busy = {}
        for other in sittings:
            if other.id == sitting.id or other.supervisor_id is None:
                continue
            if not _exam_sitting_times_overlap(sitting, other):
                continue
            busy[other.supervisor_id] = other.academic_class.name
        options = []
        for teacher in teachers:
            busy_class = busy.get(teacher.id)
            options.append(
                {
                    "id": teacher.id,
                    "name": f"{teacher.first_name} {teacher.last_name}".strip(),
                    "available": busy_class is None,
                    "busy_class": busy_class or "",
                    "selected": teacher.id == sitting.supervisor_id,
                }
            )
        choices[str(sitting.id)] = options
    return choices


def _current_academic_calendar():
    year = (
        AcademicYear.objects.filter(is_current=True, status=AcademicYear.Status.ACTIVE)
        .prefetch_related(
            Prefetch("terms", queryset=AcademicTerm.objects.order_by("order", "start_date", "name"))
        )
        .first()
    )
    if year is None:
        year = (
            AcademicYear.objects.filter(status=AcademicYear.Status.ACTIVE)
            .prefetch_related(
                Prefetch("terms", queryset=AcademicTerm.objects.order_by("order", "start_date", "name"))
            )
            .order_by("-start_date", "name")
            .first()
        )
    terms = list(year.terms.all()) if year else []
    today = date.today()
    current_term = next((term for term in terms if term.is_current), None)
    if current_term is None:
        current_term = next(
            (term for term in terms if term.start_date <= today <= term.end_date),
            terms[0] if terms else None,
        )
    return year, terms, current_term


def _registered_academic_years():
    return list(
        AcademicYear.objects.filter(status=AcademicYear.Status.ACTIVE)
        .prefetch_related(
            Prefetch("terms", queryset=AcademicTerm.objects.order_by("order", "start_date", "name"))
        )
        .order_by("-is_current", "-start_date", "name")
    )


def _default_term_for_year(year):
    terms = list(year.terms.all()) if year else []
    if not terms:
        return None
    current = next((term for term in terms if term.is_current), None)
    if current:
        return current
    today = date.today()
    return next(
        (term for term in terms if term.start_date <= today <= term.end_date),
        terms[0],
    )


def _parse_exam_date(value):
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


@login_required
@require_http_methods(["GET", "POST"])
def exam_timetable_generation(request, page=None):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = page or _it_support_exam_page("exam-timetable-generation")
    levels, allocations, supervisor_ids = _exam_timetable_generation_levels()
    viable_ids = {level.id for level in levels if level.is_viable}
    academic_years = _registered_academic_years()
    years_by_id = {str(year.id): year for year in academic_years}
    default_year = next((year for year in academic_years if year.is_current), None)
    if default_year is None and academic_years:
        default_year = academic_years[0]
    selected_year_id = str(default_year.id) if default_year else ""
    academic_year = default_year
    academic_terms = list(default_year.terms.all()) if default_year else []
    default_term = _default_term_for_year(default_year)
    calendar_ready = bool(academic_years and any(list(year.terms.all()) for year in academic_years))
    open_generate_modal = False
    generate_step = 1
    selected_term_id = default_term.id if default_term else ""
    exam_name = ""
    exam_start_date = ""
    if request.method == "GET" and request.GET.get("generate"):
        open_generate_modal = True

    if request.method == "POST":
        selected_ids = []
        for raw_id in request.POST.getlist("level_id"):
            try:
                selected_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        selected_ids = [level_id for level_id in selected_ids if level_id in viable_ids]
        selected_year_id = (request.POST.get("academic_year_id") or "").strip()
        selected_term_id = (request.POST.get("academic_term_id") or "").strip()
        exam_name = (request.POST.get("exam_name") or "").strip().upper()
        exam_start_date = (request.POST.get("exam_start_date") or "").strip()
        academic_year = years_by_id.get(selected_year_id)
        academic_terms = list(academic_year.terms.all()) if academic_year else []
        if not selected_ids:
            error(request, "Select at least one viable academic level to generate an assessment timetable.")
            open_generate_modal = True
            generate_step = 1
        elif not calendar_ready:
            error(
                request,
                "Register an academic year and its terms in academic calendar settings before generating an assessment timetable.",
            )
            open_generate_modal = True
            generate_step = 2
        else:
            term = next(
                (item for item in academic_terms if str(item.id) == str(selected_term_id)),
                None,
            )
            start = _parse_exam_date(exam_start_date)
            if academic_year is None:
                error(request, "Select a registered academic year.")
                open_generate_modal = True
                generate_step = 2
            elif term is None:
                error(request, "Select an academic term from the selected academic year.")
                open_generate_modal = True
                generate_step = 2
            elif not exam_name:
                error(request, "Enter a name for this assessment.")
                open_generate_modal = True
                generate_step = 2
            elif start is None:
                error(request, "Select when the assessment starts.")
                open_generate_modal = True
                generate_step = 2
            elif start < term.start_date or start > term.end_date:
                error(
                    request,
                    f"The assessment start date must fall inside {term.name} ({term.start_date:%d %b %Y} to {term.end_date:%d %b %Y}).",
                )
                open_generate_modal = True
                generate_step = 2
            else:
                selected_levels = [level for level in levels if level.id in selected_ids]
                exam_dates_by_level = {}
                overflow = []
                end = start
                for level in selected_levels:
                    dates = exam_dates_for_subjects(
                        start,
                        len(level.generation_subjects),
                        level.schedule_periods,
                        term.end_date,
                    )
                    if dates is None:
                        overflow.append(level)
                        continue
                    exam_dates_by_level[level.id] = dates
                    if dates:
                        end = max(end, dates[-1])
                if overflow:
                    names = ", ".join(level.name for level in overflow)
                    error(
                        request,
                        f"Assessments for {names} cannot fit inside {term.name} from {start:%d %b %Y}. "
                        f"Each subject needs one session, so choose an earlier start date.",
                    )
                    open_generate_modal = True
                    generate_step = 2
                else:
                    class_ids = [
                        academic_class.id
                        for level in selected_levels
                        for academic_class in level.generation_classes
                    ]
                    with transaction.atomic():
                        GeneratedExamSitting.objects.filter(academic_class_id__in=class_ids).delete()
                        generation = GeneratedExamTimetable.objects.create(
                            name=exam_name,
                            created_by=request.user,
                            academic_year=academic_year,
                            academic_term=term,
                            start_date=start,
                            end_date=end,
                            status=_initial_exam_status(),
                        )
                        generation.academic_levels.set(selected_levels)
                        sitting_count, total_slots = _generate_exams_for_levels(
                            generation,
                            selected_levels,
                            allocations,
                            supervisor_ids,
                            exam_dates_by_level=exam_dates_by_level,
                        )
                    names = ", ".join(level.name for level in selected_levels)
                    blank_count = max(total_slots - sitting_count, 0)
                    if blank_count:
                        detail = (
                            f"{sitting_count} exam{'' if sitting_count == 1 else 's'} placed, "
                            f"{blank_count} left blank to avoid supervisor collisions."
                        )
                    else:
                        detail = (
                            f"{sitting_count} exam{'' if sitting_count == 1 else 's'} created "
                            f"with each subject in one session."
                        )
                    success(
                        request,
                        f"{exam_name} timetable generated for {names} in {academic_year.name} {term.name} "
                        f"({start:%d %b %Y} to {end:%d %b %Y}). {detail}",
                    )
                    return redirect("employees:it_support_exam_page", tool="exam-timetable-generation")

    terms_by_year = {
        str(year.id): [
            {
                "id": term.id,
                "name": term.name,
                "start": term.start_date.isoformat(),
                "end": term.end_date.isoformat(),
                "label": (
                    f"{term.name} ({term.start_date:%d %b %Y} – {term.end_date:%d %b %Y})"
                ),
            }
            for term in year.terms.all()
        ]
        for year in academic_years
    }

    return render(
        request,
        "employees/it_support_exam_timetable_generation.html",
        {
            "active_nav": "dashboard",
            "page": current,
            "active_exam_tool": "exam-timetable-generation",
            "level_groups": group_academic_levels_by_category(levels),
            "viable_count": len(viable_ids),
            "open_generate_modal": open_generate_modal,
            "generate_step": generate_step,
            "academic_years": academic_years,
            "academic_year": academic_year,
            "academic_terms": academic_terms,
            "terms_by_year_json": json.dumps(terms_by_year),
            "selected_year_id": str(selected_year_id) if selected_year_id else "",
            "selected_term_id": str(selected_term_id) if selected_term_id else "",
            "exam_name": exam_name,
            "exam_start_date": exam_start_date,
            "calendar_ready": calendar_ready,
            "calendar_settings_url": reverse("employees:academic_calendar_settings"),
            "timetable_groups": _generated_exam_timetables(levels),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def exam_manual_supervisor_allocation(request):
    denied = _require_it_support(request)
    if denied:
        return denied
    levels, _allocations, _supervisor_ids = _exam_timetable_generation_levels()
    teachers = list(_approved_teachers())
    teacher_ids = {teacher.id for teacher in teachers}
    class_ids = [
        academic_class.id
        for level in levels
        for academic_class in getattr(level, "generation_classes", [])
    ]
    sittings = list(
        GeneratedExamSitting.objects.filter(academic_class_id__in=class_ids)
        .select_related("academic_class", "learning_area", "supervisor")
        .order_by("exam_date", "start_time", "academic_class__order")
    )

    if request.method == "POST":
        sitting = get_object_or_404(GeneratedExamSitting, pk=request.POST.get("sitting_id"))
        raw_supervisor_id = (request.POST.get("supervisor_id") or "").strip()
        try:
            supervisor_id = int(raw_supervisor_id)
        except (TypeError, ValueError):
            supervisor_id = None
        if supervisor_id not in teacher_ids:
            error(request, "Select an available teacher for this session.")
            return redirect("employees:exam_manual_supervisor_allocation")
        others = GeneratedExamSitting.objects.filter(
            supervisor_id=supervisor_id,
            exam_date=sitting.exam_date,
        ).exclude(pk=sitting.pk).select_related("academic_class", "supervisor")
        conflict = next(
            (other for other in others if _exam_sitting_times_overlap(sitting, other)),
            None,
        )
        if conflict:
            error(
                request,
                f"{conflict.supervisor.first_name} {conflict.supervisor.last_name} is already supervising "
                f"{conflict.academic_class.name} in this session.",
            )
            return redirect("employees:exam_manual_supervisor_allocation")
        sitting.supervisor_id = supervisor_id
        sitting.save(update_fields=["supervisor"])
        success(
            request,
            f"Supervisor updated for {sitting.learning_area.code} in {sitting.academic_class.name}.",
        )
        return redirect("employees:exam_manual_supervisor_allocation")

    sitting_meta = {
        str(sitting.id): {
            "subject": sitting.learning_area.name,
            "subject_code": sitting.learning_area.code,
            "class_name": sitting.academic_class.name,
            "date_label": sitting.exam_date.strftime("%A %d %b %Y") if sitting.exam_date else sitting.weekday,
            "session": sitting.period_name,
            "time": f"{sitting.start_time.strftime('%H:%M')}–{sitting.end_time.strftime('%H:%M')}",
        }
        for sitting in sittings
    }
    return render(
        request,
        "employees/it_support_exam_manual_allocation.html",
        {
            "active_nav": "dashboard",
            "page": _it_support_exam_page("exam-timetable-generation"),
            "active_exam_tool": "exam-timetable-generation",
            "manual_allocation": True,
            "timetable_groups": _generated_exam_timetables(levels),
            "supervisor_choices": _exam_supervisor_options_by_sitting(sittings, teachers),
            "sitting_meta": sitting_meta,
        },
    )


def _coverage_pct(part, whole):
    if not whole:
        return 0
    return round((part * 100) / whole)


def _timetable_analytics_context():
    active_classes = AcademicClass.objects.filter(status=AcademicClass.Status.ACTIVE).order_by("order", "name")
    profiles = list(
        LearningScheduleProfile.objects.filter(kind=LearningScheduleProfile.Kind.LEARNING)
        .prefetch_related(
            "activities",
            Prefetch(
                "academic_levels",
                queryset=AcademicLevel.objects.filter(status=AcademicLevel.Status.ACTIVE)
                .prefetch_related(Prefetch("classes", queryset=active_classes))
                .order_by("order", "name"),
            ),
        )
    )
    period_profiles = []
    total_weekly_periods = 0
    total_class_period_slots = 0
    for profile in profiles:
        preview = build_schedule_preview(
            profile.first_class_start_time,
            profile.lesson_duration_minutes,
            profile.activities.all(),
            last_class_end=profile.last_class_end_time,
            study_days=profile.study_days,
        )
        lesson_blocks = [block for block in preview["blocks"] if block["kind"] == "lesson"]
        activity_blocks = [block for block in preview["blocks"] if block["kind"] == "activity"]
        study_days = list(preview["days"] or [])
        periods_per_day = len(lesson_blocks)
        weekly_periods = periods_per_day * len(study_days)
        class_count = sum(len(level.classes.all()) for level in profile.academic_levels.all())
        class_period_slots = weekly_periods * class_count
        total_weekly_periods += weekly_periods
        total_class_period_slots += class_period_slots
        period_profiles.append(
            {
                "profile": profile,
                "ready": preview["ready"],
                "study_days": study_days,
                "periods_per_day": periods_per_day,
                "weekly_periods": weekly_periods,
                "activity_count": len(activity_blocks),
                "class_count": class_count,
                "class_period_slots": class_period_slots,
                "lessons": lesson_blocks,
            }
        )
    period_profiles.sort(key=lambda item: (-item["class_period_slots"], item["profile"].name))

    allocation_qs = ClassSubjectAllocation.objects.select_related(
        "teacher",
        "academic_class",
        "academic_class__academic_level",
        "learning_area",
    )
    teachers = list(
        _approved_teachers()
        .annotate(
            allocation_count=Count("subject_allocations", distinct=True),
            allocated_class_count=Count("subject_allocations__academic_class", distinct=True),
            allocated_subject_count=Count("subject_allocations__learning_area", distinct=True),
        )
        .prefetch_related(
            Prefetch(
                "subject_allocations",
                queryset=allocation_qs.order_by(
                    "academic_class__academic_level__order",
                    "academic_class__order",
                    "learning_area__display_order",
                    "learning_area__name",
                ),
            )
        )
    )
    assigned_teacher_count = sum(1 for teacher in teachers if teacher.allocation_count)
    max_teacher_load = max((teacher.allocation_count for teacher in teachers), default=0)
    for teacher in teachers:
        teacher.load_pct = _coverage_pct(teacher.allocation_count, max_teacher_load) if max_teacher_load else 0
    teachers.sort(key=lambda teacher: (-teacher.allocation_count, teacher.last_name, teacher.first_name))

    subjects = list(
        LearningArea.objects.filter(status=LearningArea.Status.ACTIVE)
        .prefetch_related(
            Prefetch(
                "academic_levels",
                queryset=AcademicLevel.objects.filter(status=AcademicLevel.Status.ACTIVE)
                .prefetch_related(Prefetch("classes", queryset=active_classes))
                .order_by("order", "name"),
            ),
            Prefetch(
                "class_allocations",
                queryset=ClassSubjectAllocation.objects.select_related(
                    "teacher",
                    "academic_class",
                    "academic_class__academic_level",
                ),
            ),
        )
        .order_by("display_order", "name")
    )
    subject_rows = []
    expected_slots = 0
    assigned_slots = 0
    for subject in subjects:
        slots = sum(len(level.classes.all()) for level in subject.academic_levels.all())
        assigned = list(subject.class_allocations.all())
        expected_slots += slots
        assigned_slots += len(assigned)
        teacher_ids = {item.teacher_id for item in assigned}
        assigned_count = len(assigned)
        unassigned = max(slots - assigned_count, 0)
        if not slots:
            status = "idle"
        elif unassigned == 0:
            status = "complete"
        elif assigned_count == 0:
            status = "empty"
        else:
            status = "gaps"
        subject_rows.append(
            {
                "subject": subject,
                "expected": slots,
                "assigned": assigned_count,
                "unassigned": unassigned,
                "coverage": _coverage_pct(assigned_count, slots),
                "status": status,
                "teacher_count": len(teacher_ids),
                "allocations": assigned,
            }
        )
    subject_rows.sort(key=lambda row: (-row["unassigned"], row["subject"].name))

    return {
        "period_profiles": period_profiles,
        "period_totals": {
            "profiles": len(period_profiles),
            "ready_profiles": sum(1 for item in period_profiles if item["ready"]),
            "weekly_periods": total_weekly_periods,
            "class_period_slots": total_class_period_slots,
        },
        "teachers": teachers,
        "teacher_totals": {
            "teachers": len(teachers),
            "assigned_teachers": assigned_teacher_count,
            "allocations": sum(teacher.allocation_count for teacher in teachers),
            "coverage": _coverage_pct(assigned_teacher_count, len(teachers)),
        },
        "subjects": subject_rows,
        "subject_totals": {
            "subjects": len(subject_rows),
            "expected": expected_slots,
            "assigned": assigned_slots,
            "unassigned": max(expected_slots - assigned_slots, 0),
            "coverage": _coverage_pct(assigned_slots, expected_slots),
        },
    }


@login_required
def timetable_analytics(request, page=None):
    denied = _require_it_support(request)
    if denied:
        return denied
    current = page or _it_support_timetable_page("timetable-analytics")
    context = _timetable_analytics_context()
    context.update(
        {
            "active_nav": "dashboard",
            "page": current,
            "active_timetable_tool": "timetable-analytics",
        }
    )
    return render(request, "employees/it_support_timetable_analytics.html", context)


@login_required
def system_settings(request):
    if uses_profile_settings(workspace_role(request)):
        return redirect("employees:profile_settings")
    return render(
        request,
        "employees/system_settings.html",
        {"active_nav": "settings", "active_settings": ""},
    )


@login_required
@require_http_methods(["GET", "POST"])
def profile_settings(request):
    if not uses_profile_settings(workspace_role(request)):
        return redirect("employees:system_settings")

    employee = request.user
    account_form = EmployeeAccountSettingsForm(
        request.POST or None,
        request.FILES or None,
        instance=employee,
    )
    password_form = EmployeePasswordChangeForm(user=employee)

    if request.method == "POST":
        form_type = (request.POST.get("form_type") or "").strip()
        if form_type == "account" and account_form.is_valid():
            account_form.save()
            success(request, "Profile updated.")
            return redirect("employees:profile_settings")
        if form_type == "password":
            password_form = EmployeePasswordChangeForm(user=employee, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                success(request, "Password updated.")
                return redirect("employees:profile_settings")

    phone_country, phone_national = parse_stored_phone(employee.phone_number)
    return render(
        request,
        "employees/settings_profile.html",
        {
            "active_nav": "settings",
            "account_form": account_form,
            "password_form": password_form,
            "phone_countries_json": list(PHONE_COUNTRIES),
            "phone_country": phone_country,
            "phone_national": phone_national,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def school_profile_settings(request):
    profile, _ = SchoolProfile.objects.get_or_create(pk=1)
    form = SchoolProfileForm(
        request.POST or None,
        request.FILES or None,
        instance=profile,
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        success(request, "School profile saved.")
        return redirect("employees:school_profile_settings")

    return render(
        request,
        "employees/settings_school_profile.html",
        {
            "active_nav": "settings",
            "active_settings": "school",
            "form": form,
            "school_profile": profile,
        },
    )


def _school_profile_section(
    request,
    form_class,
    title,
    description,
    redirect_name,
    current_enrollment=None,
):
    profile, _ = SchoolProfile.objects.get_or_create(pk=1)
    form = form_class(request.POST or None, request.FILES or None, instance=profile)

    if request.method == "POST" and form.is_valid():
        form.save()
        success(request, f"{title} saved.")
        return redirect(redirect_name)

    return render(
        request,
        "employees/settings_school_profile_section.html",
        {
            "active_nav": "settings",
            "active_settings": "school",
            "form": form,
            "section_title": title,
            "section_description": description,
            "current_enrollment": current_enrollment,
            "school_profile": profile,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def school_profile_contact_location_settings(request):
    return _school_profile_section(
        request,
        SchoolProfileContactLocationForm,
        "Contact & location",
        "Set the school address, map coordinates, public contact channels, and online links.",
        "employees:school_profile_contact_location_settings",
    )


@login_required
@require_http_methods(["GET", "POST"])
def school_profile_branding_settings(request):
    return _school_profile_section(
        request,
        SchoolProfileBrandingForm,
        "Branding",
        "Upload the school logo used on assessment reports, then set motto, vision, mission, and colour.",
        "employees:school_profile_branding_settings",
    )


@login_required
@require_http_methods(["GET", "POST"])
def school_profile_leadership_settings(request):
    return _school_profile_section(
        request,
        SchoolProfileLeadershipForm,
        "Leadership & structure",
        "Record the school leadership, administrative team, governance details, and departments.",
        "employees:school_profile_leadership_settings",
    )


@login_required
@require_http_methods(["GET", "POST"])
def school_profile_academic_setup_settings(request):
    return _school_profile_section(
        request,
        SchoolProfileAcademicSetupForm,
        "Academic setup",
        "Set the levels and streams offered, term structure, and academic year dates.",
        "employees:school_profile_academic_setup_settings",
    )


@login_required
@require_http_methods(["GET", "POST"])
def school_profile_operations_settings(request):
    return _school_profile_section(
        request,
        SchoolProfileOperationsForm,
        "Capacity & operations",
        "Set enrollment capacity, boarding arrangements, and available transport routes.",
        "employees:school_profile_operations_settings",
        current_enrollment=Student.objects.count(),
    )


@login_required
@require_http_methods(["GET", "POST"])
def school_profile_financial_settings(request):
    return _school_profile_section(
        request,
        SchoolProfileFinancialForm,
        "Financial",
        "Set the payment details and reference used when configuring fee schedules.",
        "employees:school_profile_financial_settings",
    )


@login_required
@require_http_methods(["GET", "POST"])
def school_profile_compliance_settings(request):
    return _school_profile_section(
        request,
        SchoolProfileComplianceForm,
        "Compliance & documents",
        "Store the current registration certificate and an optional recent inspection report.",
        "employees:school_profile_compliance_settings",
    )


@login_required
@require_http_methods(["GET", "POST"])
def academic_calendar_settings(request):
    form = AcademicYearForm(request.POST or None)
    open_register_modal = False
    term_rows = []
    term_errors = []

    if request.method == "POST":
        try:
            term_rows = parse_academic_term_rows(request.POST)
        except ValidationError as exc:
            term_errors = list(exc.messages)
            open_register_modal = True
        if form.is_valid() and not term_errors:
            try:
                with transaction.atomic():
                    academic_year = form.save()
                    sync_academic_terms(academic_year, term_rows)
            except ValidationError as exc:
                term_errors = list(exc.messages)
                open_register_modal = True
            else:
                success(request, f"Academic year {academic_year.name} registered.")
                return redirect("employees:academic_calendar_settings")
        else:
            open_register_modal = True

    years = list(
        AcademicYear.objects.prefetch_related(
            Prefetch("terms", queryset=AcademicTerm.objects.order_by("order", "start_date"))
        )
    )
    current_year = next((year for year in years if year.is_current), None)
    all_terms = [term for year in years for term in year.terms.all()]
    current_term = next((term for term in all_terms if term.is_current), None)
    return render(
        request,
        "employees/settings_academic_calendar.html",
        {
            "active_nav": "settings",
            "active_settings": "calendar",
            "form": form,
            "years": years,
            "current_year": current_year,
            "all_terms": all_terms,
            "current_term": current_term,
            "term_rows": term_rows,
            "term_errors": term_errors,
            "open_register_modal": open_register_modal,
        },
    )


@login_required
def curriculum_settings(request):
    return render(
        request,
        "employees/settings_curriculum.html",
        {"active_nav": "settings", "active_settings": "curriculum"},
    )


def _schedule_timetable_settings(
    request,
    *,
    kind,
    list_url_name,
    delete_url_name,
    template_name,
    page_title,
    nav_label,
    config_heading,
    config_copy,
    kicker,
    empty_message,
    day_section_heading,
    active_flag,
    period_label="Lesson",
    start_caption="first class",
    end_caption="lesson end time",
    success_label="Academic schedule profile",
):
    edit_profile = None
    edit_id = request.GET.get("edit") or request.POST.get("profile_id")
    if edit_id and str(edit_id).isdigit():
        edit_profile = (
            LearningScheduleProfile.objects.prefetch_related("activities")
            .filter(pk=edit_id, kind=kind)
            .first()
        )

    profile_form = LearningScheduleProfileForm(
        request.POST or None,
        instance=edit_profile,
        schedule_kind=kind,
    )
    activity_queryset = (
        LearningScheduleActivity.objects.filter(profile=edit_profile)
        if edit_profile
        else LearningScheduleActivity.objects.none()
    )
    activity_formset = LearningScheduleActivityFormSet(
        request.POST or None,
        queryset=activity_queryset,
        prefix="activities",
    )
    if request.method == "POST":
        profile_valid = profile_form.is_valid()
        activities_valid = activity_formset.is_valid()
        submitted_activities = [
            form
            for form in activity_formset
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ] if activities_valid else []

        if profile_valid and activities_valid and submitted_activities:
            with transaction.atomic():
                profile = profile_form.save()
                activities = activity_formset.save(commit=False)
                for activity in activity_formset.deleted_objects:
                    activity.delete()
                for order, activity in enumerate(activities, start=1):
                    activity.profile = profile
                    activity.order = order
                    activity.save()
            success(
                request,
                f"{success_label} {profile.name} "
                f"{'updated' if edit_profile else 'registered'}.",
            )
            return redirect(list_url_name)
        if not submitted_activities and activities_valid:
            profile_form.add_error(None, "Add at least one timetable activity.")
        error(request, "The schedule profile could not be saved. Check the details below.")

    profiles = list(
        LearningScheduleProfile.objects.filter(kind=kind).prefetch_related(
            "academic_levels",
            "activities",
        )
    )
    for profile in profiles:
        profile.day_preview = build_schedule_preview(
            profile.first_class_start_time,
            profile.lesson_duration_minutes,
            profile.activities.all(),
            last_class_end=profile.last_class_end_time,
            study_days=profile.study_days,
            period_label=period_label,
            start_caption=start_caption,
            end_caption=end_caption,
        )
    return render(
        request,
        template_name,
        {
            "active_nav": "settings",
            "active_settings": "curriculum",
            active_flag: True,
            "page_title": page_title,
            "nav_label": nav_label,
            "config_heading": config_heading,
            "config_copy": config_copy,
            "kicker": kicker,
            "empty_message": empty_message,
            "day_section_heading": day_section_heading,
            "list_url_name": list_url_name,
            "delete_url_name": delete_url_name,
            "period_label": period_label,
            "start_caption": start_caption,
            "end_caption": end_caption,
            "profile_name_suffix": (
                " E-LEARNING SESSION"
                if kind == LearningScheduleProfile.Kind.ELEARNING
                else " SESSION"
            ),
            "profile_form": profile_form,
            "activity_formset": activity_formset,
            "edit_profile": edit_profile,
            "open_profile_modal": bool(edit_profile)
            or (request.method == "POST" and (profile_form.errors or activity_formset.errors)),
            "profiles": profiles,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def learning_timetable_settings(request):
    return _schedule_timetable_settings(
        request,
        kind=LearningScheduleProfile.Kind.LEARNING,
        list_url_name="employees:learning_timetable_settings",
        delete_url_name="employees:delete_learning_timetable_profile",
        template_name="employees/settings_learning_timetable.html",
        page_title="Learning timetable settings",
        nav_label="Learning timetable",
        config_heading="Academic schedule configuration",
        config_copy="Set the school-day structure for each academic level category before generating learning timetables.",
        kicker="Learning timetable",
        empty_message="No schedule profiles yet. Register a profile to configure learning days, class timings, and activities.",
        day_section_heading="2. Learning day",
        active_flag="learning_timetable_active",
        period_label="Lesson",
        start_caption="first class",
        end_caption="lesson end time",
        success_label="Academic schedule profile",
    )


@login_required
@require_POST
def delete_learning_timetable_profile(request, profile_id):
    profile = get_object_or_404(
        LearningScheduleProfile,
        pk=profile_id,
        kind=LearningScheduleProfile.Kind.LEARNING,
    )
    name = profile.name
    profile.delete()
    success(request, f"Academic schedule profile {name} deleted.")
    return redirect("employees:learning_timetable_settings")


@login_required
@require_http_methods(["GET", "POST"])
def elearning_timetable_settings(request):
    return _schedule_timetable_settings(
        request,
        kind=LearningScheduleProfile.Kind.ELEARNING,
        list_url_name="employees:elearning_timetable_settings",
        delete_url_name="employees:delete_elearning_timetable_profile",
        template_name="employees/settings_elearning_timetable.html",
        page_title="E-learning timetable settings",
        nav_label="E-learning timetable",
        config_heading="E-learning schedule configuration",
        config_copy="Set the weekly session structure for each academic level category before generating e-learning timetables.",
        kicker="E-learning timetable",
        empty_message="No e-learning schedule profiles yet. Register a profile to configure study days, session timings, and activities.",
        day_section_heading="2. E-learning day",
        active_flag="elearning_timetable_active",
        period_label="Session",
        start_caption="first session",
        end_caption="session end time",
        success_label="E-learning schedule profile",
    )


@login_required
@require_POST
def delete_elearning_timetable_profile(request, profile_id):
    profile = get_object_or_404(
        LearningScheduleProfile,
        pk=profile_id,
        kind=LearningScheduleProfile.Kind.ELEARNING,
    )
    name = profile.name
    profile.delete()
    success(request, f"E-learning schedule profile {name} deleted.")
    return redirect("employees:elearning_timetable_settings")


@login_required
@require_http_methods(["GET", "POST"])
def academic_levels_settings(request):
    form = AcademicLevelForm(request.POST or None)
    open_register_modal = False
    class_rows = []
    class_errors = []

    if request.method == "POST":
        class_rows = parse_academic_class_rows(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    level = form.save()
                    sync_academic_classes(level, class_rows)
            except ValidationError as exc:
                class_errors = list(exc.messages)
                open_register_modal = True
            else:
                success(request, "Academic level registered.")
                return redirect("employees:academic_levels_settings")
        else:
            open_register_modal = True

    levels = list(
        AcademicLevel.objects.prefetch_related(
            Prefetch(
                "classes",
                queryset=AcademicClass.objects.order_by("order", "name"),
            )
        ).order_by("order", "name")
    )
    category_suggestions = (
        AcademicLevel.objects.exclude(category="")
        .values_list("category", flat=True)
        .distinct()
        .order_by("category")
    )
    return render(
        request,
        "employees/settings_academic_levels.html",
        {
            "active_nav": "settings",
            "active_settings": "curriculum",
            "form": form,
            "levels": levels,
            "level_groups": group_academic_levels_by_category(levels),
            "category_suggestions": category_suggestions,
            "open_register_modal": open_register_modal,
            "class_rows": class_rows,
            "class_errors": class_errors,
        },
    )


@login_required
@require_POST
def reorder_academic_levels(request):
    ordered_ids = [value for value in request.POST.getlist("level_id") if value.isdigit()]
    if not ordered_ids or len(ordered_ids) != len(set(ordered_ids)):
        error(request, "No academic levels were provided to reorder.")
        return redirect("employees:academic_levels_settings")

    levels_by_id = {
        str(level.id): level for level in AcademicLevel.objects.filter(pk__in=ordered_ids)
    }
    if len(levels_by_id) != len(ordered_ids):
        error(request, "One or more academic levels could not be found.")
        return redirect("employees:academic_levels_settings")

    existing_ids = set(AcademicLevel.objects.values_list("id", flat=True))
    if {int(level_id) for level_id in ordered_ids} != existing_ids:
        error(request, "Reorder the full list of academic levels before saving.")
        return redirect("employees:academic_levels_settings")

    with transaction.atomic():
        for index, level_id in enumerate(ordered_ids, start=1):
            level = levels_by_id[level_id]
            if level.order != index:
                level.order = index
                level.save(update_fields=["order", "updated_at"])

    success(request, "Academic level order saved.")
    return redirect("employees:academic_levels_settings")


@login_required
@require_http_methods(["GET", "POST"])
def learning_areas_settings(request):
    form = LearningAreaForm(request.POST or None)
    open_register_modal = False

    if request.method == "POST":
        if form.is_valid():
            form.save()
            success(request, "Learning area registered.")
            return redirect("employees:learning_areas_settings")
        open_register_modal = True

    areas = list(
        LearningArea.objects.prefetch_related(
            Prefetch(
                "academic_levels",
                queryset=AcademicLevel.objects.order_by("order", "name"),
            )
        ).all()
    )
    academic_levels = AcademicLevel.objects.order_by("category", "order", "name")
    return render(
        request,
        "employees/settings_learning_areas.html",
        {
            "active_nav": "settings",
            "active_settings": "curriculum",
            "form": form,
            "areas": areas,
            "area_groups": group_learning_areas_by_category(areas),
            "academic_levels": academic_levels,
            "open_register_modal": open_register_modal,
        },
    )


def _exam_nav_levels():
    return list(
        AcademicLevel.objects.filter(status=AcademicLevel.Status.ACTIVE).order_by(
            "category", "order", "name"
        )
    )


def _build_exam_subjects(level):
    settings_by_area = {
        setting.learning_area_id: setting for setting in level.exam_subject_settings.all()
    }
    return sorted(
        [
            {
                "area": area,
                "setting": settings_by_area.get(area.id),
                "out_of_marks": (
                    settings_by_area[area.id].out_of_marks
                    if area.id in settings_by_area
                    else area.total_marks
                ),
                "display_order": (
                    settings_by_area[area.id].display_order
                    if area.id in settings_by_area
                    else area.display_order
                ),
            }
            for area in level.learning_areas.all()
        ],
        key=lambda subject: (
            subject["display_order"],
            subject["area"].display_order,
            subject["area"].code.lower(),
            subject["area"].name.lower(),
        ),
    )


def _redirect_exam_level(level_id, request=None):
    if request is not None and request.POST.get("redirect_to") == "combinations":
        return redirect("employees:exam_subject_combination_level", level_id=level_id)
    return redirect("employees:exam_level_settings", level_id=level_id)


@login_required
@require_http_methods(["GET", "POST"])
def exam_timetable_settings(request):
    edit_profile = None
    edit_id = request.GET.get("edit") or request.POST.get("profile_id")
    if edit_id and str(edit_id).isdigit():
        edit_profile = (
            ExamScheduleProfile.objects.prefetch_related("activities", "sessions")
            .filter(pk=edit_id)
            .first()
        )

    profile_form = ExamScheduleProfileForm(
        request.POST or None,
        instance=edit_profile,
    )
    activity_queryset = (
        ExamScheduleActivity.objects.filter(profile=edit_profile)
        if edit_profile
        else ExamScheduleActivity.objects.none()
    )
    activity_formset = ExamScheduleActivityFormSet(
        request.POST or None,
        queryset=activity_queryset,
        prefix="activities",
    )
    if request.method == "POST":
        profile_valid = profile_form.is_valid()
        activities_valid = activity_formset.is_valid()
        if profile_valid and activities_valid:
            with transaction.atomic():
                profile = profile_form.save()
                activities = activity_formset.save(commit=False)
                for activity in activity_formset.deleted_objects:
                    activity.delete()
                for order, activity in enumerate(activities, start=1):
                    activity.profile = profile
                    activity.order = order
                    activity.save()
                preview = build_schedule_preview(
                    profile.first_exam_start_time,
                    profile.exam_session_duration_minutes,
                    profile.activities.all(),
                    last_class_end=profile.last_exam_end_time,
                    period_label="Session",
                    day_labels=["Assessment day"],
                    start_caption="first assessment",
                    end_caption="assessment end time",
                )
                profile.sessions.all().delete()
                session_order = 0
                for block in preview["blocks"]:
                    if block["kind"] != "lesson":
                        continue
                    session_order += 1
                    ExamTimetableSession.objects.create(
                        profile=profile,
                        name=block["label"].upper(),
                        start_time=minutes_to_time(block["start"]),
                        duration_minutes=block["end"] - block["start"],
                        order=session_order,
                    )
            success(
                request,
                f"Assessment timetable profile {profile.name} "
                f"{'updated' if edit_profile else 'registered'}.",
            )
            return redirect("employees:exam_timetable_settings")
        error(request, "The assessment timetable profile could not be saved. Check the details below.")

    profiles = list(
        ExamScheduleProfile.objects.prefetch_related(
            "academic_levels",
            "activities",
            "sessions",
        )
    )
    for profile in profiles:
        profile.day_preview = build_schedule_preview(
            profile.first_exam_start_time,
            profile.exam_session_duration_minutes,
            profile.activities.all(),
            last_class_end=profile.last_exam_end_time,
            period_label="Session",
            day_labels=["Assessment day"],
            start_caption="first assessment",
            end_caption="assessment end time",
        )
    return render(
        request,
        "employees/settings_exam_timetable.html",
        {
            "active_nav": "settings",
            "active_settings": "curriculum",
            "exam_nav_levels": _exam_nav_levels(),
            "exam_timetable_active": True,
            "profile_form": profile_form,
            "activity_formset": activity_formset,
            "edit_profile": edit_profile,
            "open_profile_modal": bool(edit_profile)
            or (
                request.method == "POST"
                and (profile_form.errors or activity_formset.errors)
            ),
            "profiles": profiles,
        },
    )


@login_required
@require_POST
def delete_exam_timetable_profile(request, profile_id):
    profile = get_object_or_404(ExamScheduleProfile, pk=profile_id)
    name = profile.name
    profile.delete()
    success(request, f"Assessment timetable profile {name} deleted.")
    return redirect("employees:exam_timetable_settings")


@login_required
@require_http_methods(["GET", "POST"])
def exam_settings(request):
    levels = _exam_nav_levels()
    for level in levels:
        level.subject_count = level.learning_areas.filter(
            status=LearningArea.Status.ACTIVE
        ).count()

    return render(
        request,
        "employees/settings_exam_settings.html",
        {
            "active_nav": "settings",
            "active_settings": "curriculum",
            "levels": levels,
            "exam_nav_levels": levels,
            "exam_level": None,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def exam_level_settings(request, level_id):
    level = get_object_or_404(
        AcademicLevel.objects.prefetch_related(
            Prefetch(
                "learning_areas",
                queryset=LearningArea.objects.filter(status=LearningArea.Status.ACTIVE).order_by(
                    "display_order", "name"
                ),
            ),
            Prefetch(
                "exam_subject_settings",
                queryset=ExamSubjectSetting.objects.select_related("learning_area"),
            ),
        ),
        pk=level_id,
        status=AcademicLevel.Status.ACTIVE,
    )
    exam_subjects = _build_exam_subjects(level)

    return render(
        request,
        "employees/settings_exam_level.html",
        {
            "active_nav": "settings",
            "active_settings": "curriculum",
            "level": level,
            "exam_level": level,
            "exam_nav_levels": _exam_nav_levels(),
            "exam_subjects": exam_subjects,
        },
    )


@login_required
@require_POST
def save_exam_subject_marks(request, level_id):
    level = get_object_or_404(AcademicLevel, pk=level_id, status=AcademicLevel.Status.ACTIVE)
    active_area_ids = set(
        level.learning_areas.filter(status=LearningArea.Status.ACTIVE).values_list("id", flat=True)
    )
    updates = []
    try:
        for area_id in active_area_ids:
            raw_marks = request.POST.get(f"marks_{area_id}", "").strip()
            if not raw_marks:
                continue
            marks = int(raw_marks)
            if marks <= 0:
                raise ValidationError("Out of marks must be greater than zero.")
            updates.append((area_id, marks))
    except (TypeError, ValueError, ValidationError):
        error(request, "Enter a whole number greater than zero for each subject.")
        return _redirect_exam_level(level_id, request)

    with transaction.atomic():
        for area_id, marks in updates:
            ExamSubjectSetting.objects.update_or_create(
                academic_level=level,
                learning_area_id=area_id,
                defaults={"out_of_marks": marks},
            )

    success(
        request,
        f"Assessment marks saved for {level.name}. Existing student scores keep their previous "
        f"out-of values until those marks are edited.",
    )
    return _redirect_exam_level(level_id, request)


@login_required
@require_POST
def reorder_exam_subjects(request, level_id):
    level = get_object_or_404(AcademicLevel, pk=level_id, status=AcademicLevel.Status.ACTIVE)
    ordered_ids = [value for value in request.POST.getlist("area_id") if value.isdigit()]
    if not ordered_ids or len(ordered_ids) != len(set(ordered_ids)):
        error(request, "No assessment subjects were provided to reorder.")
        return _redirect_exam_level(level_id)

    active_areas = {
        str(area.id): area
        for area in level.learning_areas.filter(status=LearningArea.Status.ACTIVE)
    }
    if any(area_id not in active_areas for area_id in ordered_ids):
        error(request, "One or more subjects could not be found for this academic level.")
        return _redirect_exam_level(level_id)

    with transaction.atomic():
        for index, area_id in enumerate(ordered_ids, start=1):
            area = active_areas[area_id]
            setting, created = ExamSubjectSetting.objects.get_or_create(
                academic_level=level,
                learning_area=area,
                defaults={
                    "out_of_marks": area.total_marks,
                    "display_order": index,
                },
            )
            if not created and setting.display_order != index:
                setting.display_order = index
                setting.save(update_fields=["display_order", "updated_at"])

    success(request, f"Assessment subject order saved for {level.name}.")
    return _redirect_exam_level(level_id)


@login_required
@require_POST
def create_combined_exam_subject(request, level_id):
    level = get_object_or_404(AcademicLevel, pk=level_id, status=AcademicLevel.Status.ACTIVE)
    subject_ids = []
    for value in request.POST.getlist("subject_ids"):
        if value.isdigit() and value not in subject_ids:
            subject_ids.append(value)
    name = request.POST.get("name", "").strip().upper()
    code = request.POST.get("code", "").strip().upper()

    if not name or not code or len(subject_ids) < 2:
        error(request, "Provide a name, code, and at least two subjects to combine.")
        return _redirect_exam_level(level_id, request)

    active_areas = level.learning_areas.filter(status=LearningArea.Status.ACTIVE)
    areas = {str(area.id): area for area in active_areas}
    if any(area_id not in areas for area_id in subject_ids):
        error(request, "All selected subjects must be active for this academic level.")
        return _redirect_exam_level(level_id, request)

    with transaction.atomic():
        settings = []
        for area_id in subject_ids:
            area = areas[area_id]
            setting, _ = ExamSubjectSetting.objects.get_or_create(
                academic_level=level,
                learning_area=area,
                defaults={"out_of_marks": area.total_marks},
            )
            settings.append(setting)
        try:
            combined = CombinedExamSubject.objects.create(
                academic_level=level,
                name=name,
                code=code,
            )
            CombinedExamSubjectComponent.objects.bulk_create(
                [
                    CombinedExamSubjectComponent(
                        combined_subject=combined,
                        subject_setting=setting,
                        position=index,
                    )
                    for index, setting in enumerate(settings, start=1)
                ]
            )
        except IntegrityError:
            error(request, f"A combined subject with code {code} already exists for this level.")
        else:
            success(request, f"Combined subject {name} registered for {level.name}.")
    return _redirect_exam_level(level_id, request)


@login_required
@require_POST
def delete_combined_exam_subject(request, combined_id):
    combined = get_object_or_404(CombinedExamSubject, pk=combined_id)
    level_id = combined.academic_level_id
    combined.delete()
    success(request, "Combined assessment subject removed.")
    return _redirect_exam_level(level_id, request)


@login_required
@require_http_methods(["GET"])
def exam_subject_combination_settings(request):
    levels = _exam_nav_levels()
    for level in levels:
        level.subject_count = level.learning_areas.filter(
            status=LearningArea.Status.ACTIVE
        ).count()
        level.combined_count = CombinedExamSubject.objects.filter(
            academic_level=level
        ).count()

    return render(
        request,
        "employees/settings_exam_subject_combinations.html",
        {
            "active_nav": "settings",
            "active_settings": "curriculum",
            "levels": levels,
            "exam_nav_levels": levels,
            "exam_level": None,
            "exam_combination_active": True,
        },
    )


@login_required
@require_http_methods(["GET"])
def exam_subject_combination_level(request, level_id):
    level = get_object_or_404(
        AcademicLevel.objects.prefetch_related(
            Prefetch(
                "learning_areas",
                queryset=LearningArea.objects.filter(status=LearningArea.Status.ACTIVE).order_by(
                    "display_order", "name"
                ),
            ),
            Prefetch(
                "exam_subject_settings",
                queryset=ExamSubjectSetting.objects.select_related("learning_area"),
            ),
            Prefetch(
                "combined_exam_subjects",
                queryset=CombinedExamSubject.objects.prefetch_related(
                    Prefetch(
                        "components",
                        queryset=CombinedExamSubjectComponent.objects.select_related(
                            "subject_setting__learning_area"
                        ),
                    )
                ),
            ),
        ),
        pk=level_id,
        status=AcademicLevel.Status.ACTIVE,
    )
    exam_subjects = _build_exam_subjects(level)

    return render(
        request,
        "employees/settings_exam_subject_combination_level.html",
        {
            "active_nav": "settings",
            "active_settings": "curriculum",
            "level": level,
            "exam_level": level,
            "exam_nav_levels": _exam_nav_levels(),
            "exam_subjects": exam_subjects,
            "combined_subjects": list(level.combined_exam_subjects.all()),
            "exam_combination_active": True,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def grading_system_settings(request):
    levels = _exam_nav_levels()
    grade_counts = GradeBand.objects.values("academic_level_id").annotate(
        grade_count=Count("id")
    )
    count_by_level = {
        item["academic_level_id"]: item["grade_count"] for item in grade_counts
    }
    default_count = count_by_level.get(None, 0)
    for level in levels:
        level.grade_count = count_by_level.get(level.id, 0)

    return render(
        request,
        "employees/settings_grading_system.html",
        {
            "active_nav": "settings",
            "active_settings": "curriculum",
            "exam_nav_levels": levels,
            "exam_grading_active": True,
            "levels": levels,
            "default_grade_count": default_count,
        },
    )


def _grade_bands_for_level(academic_level=None):
    return GradeBand.objects.filter(academic_level=academic_level)


def _ensure_level_grades_from_default(level):
    existing = _grade_bands_for_level(level)
    if existing.exists():
        return existing
    defaults = list(_grade_bands_for_level(None))
    if not defaults:
        return existing
    GradeBand.objects.bulk_create(
        [
            GradeBand(
                academic_level=level,
                code=band.code,
                mark_level=band.mark_level,
                meaning=band.meaning,
                points=band.points,
                start_percent=band.start_percent,
                end_percent=band.end_percent,
            )
            for band in defaults
        ]
    )
    return _grade_bands_for_level(level)


def _grading_scale_redirect(academic_level=None):
    if academic_level is None:
        return redirect("employees:grading_system_default")
    return redirect("employees:grading_level_settings", level_id=academic_level.id)


def _render_grading_scale(request, *, academic_level=None):
    if academic_level is not None:
        _ensure_level_grades_from_default(academic_level)

    edit_band = None
    edit_id = request.GET.get("edit") or request.POST.get("grade_band_id")
    if edit_id and str(edit_id).isdigit():
        edit_band = GradeBand.objects.filter(
            pk=edit_id,
            academic_level=academic_level,
        ).first()

    form = GradeBandForm(
        request.POST or None,
        instance=edit_band,
        academic_level=academic_level,
    )
    if request.method == "POST":
        if form.is_valid():
            band = form.save()
            if edit_band:
                success(request, f"Grade {band.code} updated.")
            else:
                success(request, f"Grade {band.code} registered.")
            return _grading_scale_redirect(academic_level)
        error(request, "The grade could not be saved. Check the details below.")

    open_grade_modal = bool(edit_band) or (request.method == "POST" and form.errors)
    grade_bands = _grade_bands_for_level(academic_level)

    if academic_level is None:
        page_title = "Default grading system"
        page_subtitle = (
            "Baseline grade bands used when a level has not been customized yet. "
            "Editing a level copies these defaults first, then you can change them."
        )
        back_url = reverse("employees:grading_system_settings")
    else:
        page_title = f"{academic_level.name} grading"
        page_subtitle = (
            f"{academic_level.code} · Customize grade bands for this academic level. "
            "Changes here do not affect the default system or other levels."
        )
        back_url = reverse("employees:grading_system_settings")

    return render(
        request,
        "employees/settings_grading_scale.html",
        {
            "active_nav": "settings",
            "active_settings": "curriculum",
            "exam_nav_levels": _exam_nav_levels(),
            "exam_grading_active": True,
            "form": form,
            "edit_band": edit_band,
            "open_grade_modal": open_grade_modal,
            "grade_bands": grade_bands,
            "academic_level": academic_level,
            "is_default_scale": academic_level is None,
            "page_title": page_title,
            "page_subtitle": page_subtitle,
            "back_url": back_url,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def grading_system_default(request):
    return _render_grading_scale(request, academic_level=None)


@login_required
@require_http_methods(["GET", "POST"])
def grading_level_settings(request, level_id):
    level = get_object_or_404(
        AcademicLevel,
        pk=level_id,
        status=AcademicLevel.Status.ACTIVE,
    )
    return _render_grading_scale(request, academic_level=level)


@login_required
@require_POST
def delete_grade_band(request, grade_band_id):
    grade_band = get_object_or_404(GradeBand, pk=grade_band_id)
    code = grade_band.code
    level = grade_band.academic_level
    grade_band.delete()
    success(request, f"Grade {code} deleted.")
    return _grading_scale_redirect(level)


@login_required
@require_POST
def reset_level_grading(request, level_id):
    level = get_object_or_404(
        AcademicLevel,
        pk=level_id,
        status=AcademicLevel.Status.ACTIVE,
    )
    GradeBand.objects.filter(academic_level=level).delete()
    _ensure_level_grades_from_default(level)
    success(request, f"Grades for {level.name} were reset from the default system.")
    return redirect("employees:grading_level_settings", level_id=level.id)


@login_required
@require_POST
def update_academic_level(request, level_id):
    level = get_object_or_404(AcademicLevel, pk=level_id)
    form = AcademicLevelForm(request.POST, instance=level)
    class_rows = parse_academic_class_rows(request.POST)
    if form.is_valid():
        try:
            with transaction.atomic():
                form.save()
                sync_academic_classes(level, class_rows)
        except ValidationError as exc:
            error(request, " ".join(exc.messages))
        else:
            success(request, "Academic level updated.")
    else:
        error(request, "The academic level could not be updated. Check the required fields.")
    return redirect("employees:academic_levels_settings")


@login_required
@require_POST
def toggle_academic_level_status(request, level_id):
    level = get_object_or_404(AcademicLevel, pk=level_id)
    level.status = (
        AcademicLevel.Status.INACTIVE
        if level.status == AcademicLevel.Status.ACTIVE
        else AcademicLevel.Status.ACTIVE
    )
    level.save(update_fields=["status", "updated_at"])
    success(request, f"Academic level {'suspended' if level.status == 'INACTIVE' else 'unsuspended'}.")
    return redirect("employees:academic_levels_settings")


@login_required
@require_POST
def delete_academic_level(request, level_id):
    level = get_object_or_404(AcademicLevel, pk=level_id)
    if level.learning_areas.exists():
        error(request, "This academic level is linked to learning areas and cannot be deleted.")
    elif level.classes.exists():
        error(request, "This academic level has classes and cannot be deleted. Remove the classes first.")
    else:
        level.delete()
        success(request, "Academic level deleted.")
    return redirect("employees:academic_levels_settings")


@login_required
@require_POST
def update_academic_year(request, year_id):
    academic_year = get_object_or_404(AcademicYear, pk=year_id)
    form = AcademicYearForm(request.POST, instance=academic_year)
    try:
        term_rows = parse_academic_term_rows(request.POST)
    except ValidationError as exc:
        error(request, " ".join(exc.messages))
        return redirect("employees:academic_calendar_settings")
    if form.is_valid():
        try:
            with transaction.atomic():
                form.save()
                sync_academic_terms(academic_year, term_rows)
        except ValidationError as exc:
            error(request, " ".join(exc.messages))
        else:
            success(request, f"Academic year {academic_year.name} updated.")
    else:
        error(request, "The academic year could not be updated. Check the required fields.")
    return redirect("employees:academic_calendar_settings")


@login_required
@require_POST
def delete_academic_year(request, year_id):
    academic_year = get_object_or_404(AcademicYear, pk=year_id)
    name = academic_year.name
    academic_year.delete()
    success(request, f"Academic year {name} deleted.")
    return redirect("employees:academic_calendar_settings")


@login_required
@require_POST
def set_current_academic_calendar(request):
    year_raw = request.POST.get("year_id")
    term_raw = request.POST.get("term_id")
    if year_raw is None or not str(year_raw).isdigit():
        error(request, "Select a current academic year.")
        return redirect("employees:academic_calendar_settings")
    if term_raw is None or not str(term_raw).isdigit():
        error(request, "Select a current term.")
        return redirect("employees:academic_calendar_settings")

    year = get_object_or_404(AcademicYear, pk=int(year_raw))
    term = get_object_or_404(
        AcademicTerm.objects.select_related("academic_year"),
        pk=int(term_raw),
        academic_year=year,
    )
    with transaction.atomic():
        year.is_current = True
        year.save(update_fields=["is_current", "updated_at"])
        term.is_current = True
        term.save(update_fields=["is_current", "updated_at"])
    success(request, f"Current calendar set to {year.name} · {term.name}.")
    return redirect("employees:academic_calendar_settings")


@login_required
@require_POST
def update_learning_area(request, area_id):
    area = get_object_or_404(LearningArea, pk=area_id)
    form = LearningAreaForm(request.POST, instance=area)
    if form.is_valid():
        form.save()
        success(request, "Learning area updated.")
    else:
        error(request, "The learning area could not be updated. Check the required fields.")
    return redirect("employees:learning_areas_settings")


@login_required
@require_POST
def toggle_learning_area_status(request, area_id):
    area = get_object_or_404(LearningArea, pk=area_id)
    area.status = (
        LearningArea.Status.INACTIVE
        if area.status == LearningArea.Status.ACTIVE
        else LearningArea.Status.ACTIVE
    )
    area.save(update_fields=["status", "updated_at"])
    success(request, f"Learning area {'suspended' if area.status == 'INACTIVE' else 'unsuspended'}.")
    return redirect("employees:learning_areas_settings")


@login_required
@require_POST
def delete_learning_area(request, area_id):
    area = get_object_or_404(LearningArea, pk=area_id)
    area.delete()
    success(request, "Learning area deleted.")
    return redirect("employees:learning_areas_settings")


@login_required
def finance_settings(request):
    return render(
        request,
        "employees/settings_finance.html",
        {"active_nav": "settings", "active_settings": "finance"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def admission_settings(request):
    settings_obj = AdmissionSettings.get_solo()
    form = AdmissionSettingsForm(request.POST or None, instance=settings_obj)

    if request.method == "POST" and form.is_valid():
        form.save()
        from django.core.cache import cache

        cache.delete("admissions_enabled")
        success(request, "Admission settings saved.")
        return redirect("employees:admission_settings")

    return render(
        request,
        "employees/settings_admissions.html",
        {
            "active_nav": "settings",
            "active_settings": "admissions",
            "form": form,
            "admission_settings": settings_obj,
            "suggested_next_number": AdmissionSettings.suggested_next_number(),
        },
    )


@login_required
def hr_settings(request):
    return render(
        request,
        "employees/settings_hr.html",
        {
            "active_nav": "settings",
            "active_settings": "hr",
            "active_hr_tool": "hr-settings",
        },
    )


@login_required
@require_POST
def update_profile_image(request):
    image = request.FILES.get("profile_image")
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "/dashboard/"
    if image:
        request.user.profile_image = image
        request.user.save()
        success(request, "Profile photo updated.")
    return redirect(next_url)
