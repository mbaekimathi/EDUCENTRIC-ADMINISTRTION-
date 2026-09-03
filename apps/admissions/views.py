from functools import wraps
import re

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.curriculum.models import AcademicLevel, ELearningLearningMaterial

from .forms import ParentLoginForm, StudentAdmissionForm, StudentLoginForm
from .models import AdmissionSettings, ParentGuardian, Student


def portal_session_required(session_key):
    def decorator(view):
        @wraps(view)
        def wrapped_view(request, *args, **kwargs):
            if not request.session.get(session_key):
                return redirect("admissions:portal_login")
            return view(request, *args, **kwargs)
        return wrapped_view
    return decorator


def _academic_levels_for_student_choice(choice):
    if not choice:
        return AcademicLevel.objects.none()
    levels = list(AcademicLevel.objects.filter(status=AcademicLevel.Status.ACTIVE))
    matched_ids = []
    for level in levels:
        name = (level.name or "").strip()
        slug = re.sub(r"[^A-Za-z0-9]+", "_", name).upper().strip("_")
        if slug == choice:
            matched_ids.append(level.id)
            continue
        for value, label in Student.AcademicLevel.choices:
            if value != choice:
                continue
            if label.casefold() == name.casefold():
                matched_ids.append(level.id)
            elif value.replace("_", " ").casefold() == name.casefold():
                matched_ids.append(level.id)
    if not matched_ids:
        return AcademicLevel.objects.none()
    return AcademicLevel.objects.filter(pk__in=matched_ids)


def published_materials_for_student(student):
    levels = _academic_levels_for_student_choice(student.academic_level)
    if not levels.exists():
        return ELearningLearningMaterial.objects.none()
    return (
        ELearningLearningMaterial.objects.filter(
            is_published=True,
            allocation__academic_level__in=levels,
        )
        .select_related(
            "allocation__academic_level",
            "allocation__learning_area",
        )
        .order_by(
            "allocation__learning_area__display_order",
            "allocation__learning_area__name",
            "-created_at",
            "name",
        )
    )


def published_materials_for_parent(parent):
    students = list(parent.students.filter(is_active=True, is_suspended=False))
    level_ids = set()
    for student in students:
        level_ids.update(
            _academic_levels_for_student_choice(student.academic_level).values_list("id", flat=True)
        )
    if not level_ids:
        return ELearningLearningMaterial.objects.none(), students
    materials = (
        ELearningLearningMaterial.objects.filter(
            is_published=True,
            allocation__academic_level_id__in=level_ids,
        )
        .select_related(
            "allocation__academic_level",
            "allocation__learning_area",
        )
        .order_by(
            "allocation__academic_level__order",
            "allocation__learning_area__display_order",
            "-created_at",
            "name",
        )
    )
    return materials, students


@require_http_methods(["GET", "POST"])
def admit_student(request):
    if not request.user.is_authenticated:
        return redirect("employees:login")

    admission_settings = AdmissionSettings.get_solo()
    if not admission_settings.admissions_enabled:
        return render(
            request,
            "admissions/admit_student.html",
            {
                "form": None,
                "active_nav": "admissions",
                "admission_settings": admission_settings,
                "admissions_disabled": True,
            },
        )

    form = StudentAdmissionForm(
        request.POST or None,
        request.FILES or None,
        admission_settings=admission_settings,
    )
    if request.method == "POST" and form.is_valid():
        student = form.save()
        messages.success(
            request,
            f"{student.display_name} has been admitted. "
            "Confirm their details under Pending admissions to activate portal access.",
        )
        return redirect("admissions:admit_student")
    return render(
        request,
        "admissions/admit_student.html",
        {
            "form": form,
            "active_nav": "admissions",
            "admission_settings": admission_settings,
            "next_admission_number": admission_settings.preview_next_admission_number(),
            "admissions_disabled": False,
        },
    )


@require_http_methods(["GET", "POST"])
def portal_login(request):
    student_form = StudentLoginForm(request.POST or None, prefix="student")
    parent_form = ParentLoginForm(request.POST or None, prefix="parent")

    if request.method == "POST":
        portal_type = request.POST.get("portal_type")
        if portal_type == "student" and student_form.is_valid():
            request.session["student_id"] = student_form.get_user().pk
            return redirect("admissions:student_portal")
        if portal_type == "parent" and parent_form.is_valid():
            request.session["parent_id"] = parent_form.get_user().pk
            return redirect("admissions:parent_portal")

    return render(
        request,
        "admissions/portal_login.html",
        {"student_form": student_form, "parent_form": parent_form},
    )


@portal_session_required("student_id")
def student_portal(request):
    student = get_object_or_404(
        Student,
        pk=request.session["student_id"],
        is_active=True,
        is_suspended=False,
    )
    materials = published_materials_for_student(student)
    return render(
        request,
        "admissions/student_portal.html",
        {"student": student, "learning_materials": materials},
    )


@portal_session_required("parent_id")
def parent_portal(request):
    parent = get_object_or_404(
        ParentGuardian,
        pk=request.session["parent_id"],
        is_active=True,
    )
    materials, students = published_materials_for_parent(parent)
    return render(
        request,
        "admissions/parent_portal.html",
        {
            "parent": parent,
            "learning_materials": materials,
            "linked_students": students,
        },
    )


@portal_session_required("student_id")
@require_http_methods(["GET"])
def student_portal_material_download(request, material_id):
    student = get_object_or_404(
        Student,
        pk=request.session["student_id"],
        is_active=True,
        is_suspended=False,
    )
    material = get_object_or_404(
        published_materials_for_student(student),
        pk=material_id,
    )
    return material.open_download_response()


@portal_session_required("student_id")
@require_http_methods(["GET"])
def student_portal_material_view(request, material_id):
    student = get_object_or_404(
        Student,
        pk=request.session["student_id"],
        is_active=True,
        is_suspended=False,
    )
    material = get_object_or_404(
        published_materials_for_student(student),
        pk=material_id,
    )
    return material.open_view_response()


@portal_session_required("parent_id")
@require_http_methods(["GET"])
def parent_portal_material_download(request, material_id):
    parent = get_object_or_404(
        ParentGuardian,
        pk=request.session["parent_id"],
        is_active=True,
    )
    materials, _students = published_materials_for_parent(parent)
    material = get_object_or_404(materials, pk=material_id)
    return material.open_download_response()


@portal_session_required("parent_id")
@require_http_methods(["GET"])
def parent_portal_material_view(request, material_id):
    parent = get_object_or_404(
        ParentGuardian,
        pk=request.session["parent_id"],
        is_active=True,
    )
    materials, _students = published_materials_for_parent(parent)
    material = get_object_or_404(materials, pk=material_id)
    return material.open_view_response()


def portal_logout(request):
    request.session.pop("student_id", None)
    request.session.pop("parent_id", None)
    return redirect("admissions:portal_login")
