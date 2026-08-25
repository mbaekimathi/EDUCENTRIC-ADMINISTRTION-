import csv
import re
from collections import defaultdict
from pathlib import Path

from django.db import transaction

from apps.admissions.models import Student
from apps.curriculum.models import (
    AcademicLevel,
    AcademicTerm,
    AcademicYear,
    ExamMark,
    ExamSubjectSetting,
    GeneratedExamTimetable,
    LearningArea,
)


EXAM_TYPE_DATES = {
    "OPENING": ("opening_date", "opening_date"),
    "MIDTERM": ("midterm_date", "midterm_date"),
    "CLOSING": ("closing_date", "closing_date"),
}


def import_exam_marks_csv(csv_path, *, dry_run=False):
    path = Path(csv_path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    students_by_admission = {
        str(admission).strip(): student_id
        for admission, student_id in Student.objects.exclude(admission_number__isnull=True)
        .exclude(admission_number="")
        .values_list("admission_number", "id")
    }
    subjects_by_code = {
        code.strip().upper(): subject_id
        for code, subject_id in LearningArea.objects.values_list("code", "id")
    }
    area_totals = dict(LearningArea.objects.values_list("id", "total_marks"))
    settings_out_of = {
        (level_id, area_id): out_of
        for level_id, area_id, out_of in ExamSubjectSetting.objects.values_list(
            "academic_level_id", "learning_area_id", "out_of_marks"
        )
    }
    levels = list(AcademicLevel.objects.all())

    stats = {
        "parsed": len(rows),
        "created_exams": 0,
        "reused_exams": 0,
        "created_marks": 0,
        "skipped_existing": 0,
        "skipped_missing_student": 0,
        "skipped_missing_subject": 0,
        "skipped_missing_year": 0,
        "skipped_missing_term": 0,
        "skipped_invalid_marks": 0,
        "rounded_marks": 0,
        "missing_students": set(),
        "missing_subjects": set(),
        "missing_years": set(),
        "missing_terms": set(),
    }

    year_cache = {}
    term_cache = {}
    exam_cache = {}
    pending_by_exam = defaultdict(list)
    existing_keys = set(
        ExamMark.objects.values_list("generation_id", "student_id", "learning_area_id")
    )

    for row in rows:
        admission = (row.get("admission_number") or "").strip()
        subject_code = (row.get("subject_code") or "").strip().upper()
        year_name = (row.get("academic_year") or "").strip()
        term_name = (row.get("term") or "").strip()
        exam_name = (row.get("exam_name") or "").strip()
        exam_type = (row.get("exam_type") or "").strip().upper()
        class_label = (row.get("academic_level") or "").strip()
        category = (row.get("level_category") or "").strip()

        student_id = students_by_admission.get(admission)
        if not student_id:
            stats["skipped_missing_student"] += 1
            if admission:
                stats["missing_students"].add(admission)
            continue

        subject_id = subjects_by_code.get(subject_code)
        if not subject_id:
            stats["skipped_missing_subject"] += 1
            if subject_code:
                stats["missing_subjects"].add(subject_code)
            continue

        year = _resolve_academic_year(year_name, year_cache)
        if not year:
            stats["skipped_missing_year"] += 1
            stats["missing_years"].add(year_name or "(blank)")
            continue

        term = _resolve_academic_term(year, term_name, term_cache)
        if not term:
            stats["skipped_missing_term"] += 1
            stats["missing_terms"].add(f"{year.name}:{term_name or '(blank)'}")
            continue

        marks, was_rounded = _parse_marks(row.get("marks_scored"))
        if marks is None:
            stats["skipped_invalid_marks"] += 1
            continue
        if was_rounded:
            stats["rounded_marks"] += 1

        exam_key = (year.id, term.id, exam_name.upper())
        exam = exam_cache.get(exam_key)
        if exam is None and not dry_run:
            exam, created = _get_or_create_exam(year, term, exam_name, exam_type)
            exam_cache[exam_key] = exam
            if created:
                stats["created_exams"] += 1
            else:
                stats["reused_exams"] += 1
        elif exam is None and dry_run:
            # Placeholder id for dry-run keying only.
            exam = type("ExamStub", (), {"id": f"dry-{exam_key}"})()
            if exam_key not in exam_cache:
                existing = GeneratedExamTimetable.objects.filter(
                    academic_year=year,
                    academic_term=term,
                    name__iexact=exam_name.strip(),
                ).first()
                if existing:
                    stats["reused_exams"] += 1
                else:
                    stats["created_exams"] += 1
                exam_cache[exam_key] = exam

        level = _resolve_level(class_label, category, levels)
        if level and not dry_run and hasattr(exam, "academic_levels"):
            exam.academic_levels.add(level)

        key = (exam.id, student_id, subject_id)
        if key in existing_keys:
            stats["skipped_existing"] += 1
            continue
        existing_keys.add(key)

        out_of = None
        if level is not None:
            out_of = settings_out_of.get((level.id, subject_id))
        if out_of is None:
            out_of = area_totals.get(subject_id, 100)

        pending_by_exam[exam.id].append(
            ExamMark(
                generation_id=exam.id if not dry_run else None,
                student_id=student_id,
                learning_area_id=subject_id,
                marks=marks,
                out_of_marks=out_of,
            )
        )

    if dry_run:
        stats["created_marks"] = sum(len(items) for items in pending_by_exam.values())
        _finalize_sets(stats)
        return stats

    created = 0
    with transaction.atomic():
        for exam_id, marks_list in pending_by_exam.items():
            if not marks_list or isinstance(exam_id, str):
                continue
            for mark in marks_list:
                mark.generation_id = exam_id
            ExamMark.objects.bulk_create(marks_list, batch_size=1000, ignore_conflicts=True)
            created += len(marks_list)

    stats["created_marks"] = created
    _finalize_sets(stats)
    return stats


def _finalize_sets(stats):
    for key in ("missing_students", "missing_subjects", "missing_years", "missing_terms"):
        stats[key] = sorted(stats[key])


def _resolve_academic_year(year_name, cache):
    key = (year_name or "").strip()
    if key in cache:
        return cache[key]

    candidates = []
    raw = key
    if raw:
        candidates.append(raw)
        candidates.append(raw.replace("-", "/"))
        candidates.append(raw.replace("/", "-"))
        match = re.match(r"^(\d{4})", raw)
        if match:
            candidates.append(match.group(1))

    year = None
    for candidate in candidates:
        year = AcademicYear.objects.filter(name__iexact=candidate).first()
        if year:
            break
    if year is None and not raw:
        year = AcademicYear.objects.filter(is_current=True).first()

    cache[key] = year
    return year


def _resolve_academic_term(year, term_name, cache):
    key = (year.id, (term_name or "").strip().upper())
    if key in cache:
        return cache[key]
    term = AcademicTerm.objects.filter(academic_year=year, name__iexact=term_name.strip()).first()
    cache[key] = term
    return term


def _get_or_create_exam(year, term, exam_name, exam_type):
    normalized_name = (exam_name or "").strip().upper()
    existing = GeneratedExamTimetable.objects.filter(
        academic_year=year,
        academic_term=term,
        name=normalized_name,
    ).first()
    if existing:
        return existing, False

    start_date = end_date = None
    date_fields = EXAM_TYPE_DATES.get((exam_type or "").upper())
    if date_fields:
        start_date = getattr(term, date_fields[0], None)
        end_date = getattr(term, date_fields[1], None)

    exam = GeneratedExamTimetable.objects.create(
        name=normalized_name,
        academic_year=year,
        academic_term=term,
        start_date=start_date,
        end_date=end_date,
    )
    return exam, True


def _resolve_level(class_label, category, levels):
    label = (class_label or "").strip()
    category = (category or "").strip().upper()

    digit_match = re.match(r"^(\d+)", label)
    if digit_match:
        digit = digit_match.group(1)
        for level in levels:
            if re.search(rf"(?:^|\D){re.escape(digit)}(?:\D|$)", level.name, re.I):
                if not category or level.category.upper() == category:
                    return level
        for level in levels:
            if re.search(rf"(?:^|\D){re.escape(digit)}(?:\D|$)", level.name, re.I):
                return level

    grade_match = re.match(r"^GRADE\s*(\d+)$", label, re.I)
    if grade_match:
        digit = grade_match.group(1)
        for level in levels:
            if re.search(rf"GRADE\s*{re.escape(digit)}\b", level.name, re.I) or level.code.upper() == f"G{digit}":
                return level

    if category:
        for level in levels:
            if level.category.upper() == category:
                return level
    return None


def _parse_marks(raw):
    text = (raw or "").strip()
    if not text:
        return None, False
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None, False
    if value < 0:
        return None, False
    rounded = int(round(value))
    return rounded, rounded != value

