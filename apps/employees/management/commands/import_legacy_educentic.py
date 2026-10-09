"""
Import staff (and optionally students / curriculum) from the legacy educentic
tables into the Django ADMINISTRATION schema living in the same database.

  python manage.py import_legacy_educentic
  python manage.py import_legacy_educentic --password 'YourTempPass1!'
  python manage.py import_legacy_educentic --with-students
  python manage.py import_legacy_educentic --with-curriculum
  python manage.py import_legacy_educentic --curriculum-only
  python manage.py import_legacy_educentic --assessments-only
  python manage.py import_legacy_educentic --replace
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from apps.admissions.models import ParentGuardian, Student
from apps.curriculum.models import (
    AcademicClass,
    AcademicLevel,
    AcademicTerm,
    AcademicYear,
    ExamMark,
    GeneratedExamSitting,
    GeneratedExamTimetable,
    LearningArea,
)
from apps.employees.models import Employee, EmployeeRole, IssuedEmploymentNumber, SchoolProfile


DEFAULT_PASSWORD = "Educentric1!"

ROLE_MAP = {
    "teachers": Employee.Role.TEACHER,
    "curriculum coordinator": Employee.Role.CURRICULUM_COORDINATOR,
    "academic coordinator": Employee.Role.CURRICULUM_COORDINATOR,
    "head of institution": Employee.Role.HEAD_OF_INSTITUTION,
    "principal": Employee.Role.HEAD_OF_INSTITUTION,
    "deputy head of institution": Employee.Role.DEPUTY_HEAD_OF_INSTITUTION,
    "deputy principal": Employee.Role.DEPUTY_HEAD_OF_INSTITUTION,
    "accountant": Employee.Role.ACCOUNTANT,
    "secretary": Employee.Role.SECRETARY,
    "librarian": Employee.Role.LIBRARIAN,
    "warden": Employee.Role.WARDEN,
    "store manager": Employee.Role.STORE_MANAGER,
    "technician": Employee.Role.IT_SUPPORT,
    "super admin": Employee.Role.IT_SUPPORT,
    "employee": Employee.Role.EMPLOYEE,
    "transport manager": Employee.Role.EMPLOYEE,
    "cateress": Employee.Role.EMPLOYEE,
}

TITLE_PREFIXES = {
    "MR.": Employee.Title.MR,
    "MR": Employee.Title.MR,
    "MRS.": Employee.Title.MRS,
    "MRS": Employee.Title.MRS,
    "MISS": Employee.Title.MISS,
    "MS.": Employee.Title.MS,
    "MS": Employee.Title.MS,
    "DR.": Employee.Title.DR,
    "DR": Employee.Title.DR,
    "PROF.": Employee.Title.PROF,
    "PROF": Employee.Title.PROF,
    "TR.": Employee.Title.TR,
    "TR": Employee.Title.TR,
}

GRADE_MAP = {
    "GRADE 1": Student.AcademicLevel.GRADE_1,
    "GRADE 2": Student.AcademicLevel.GRADE_2,
    "GRADE 3": Student.AcademicLevel.GRADE_3,
    "GRADE 4": Student.AcademicLevel.GRADE_4,
    "GRADE 5": Student.AcademicLevel.GRADE_5,
    "GRADE 6": Student.AcademicLevel.GRADE_6,
    "GRADE 7": Student.AcademicLevel.GRADE_7,
    "GRADE 8": Student.AcademicLevel.GRADE_8,
    "GRADE 9": Student.AcademicLevel.GRADE_9,
}


def _normalize_phone(raw: str) -> str:
    phone = re.sub(r"[^\d+]", "", (raw or "").strip())
    if phone.startswith("254") and not phone.startswith("+"):
        phone = f"+{phone}"
    elif phone.startswith("0") and len(phone) >= 10:
        phone = f"+254{phone[1:]}"
    elif phone.isdigit() and len(phone) == 9:
        phone = f"+254{phone}"
    return phone[:24] or "+254700000000"


def _parse_name(full_name: str):
    parts = [p for p in re.split(r"\s+", (full_name or "").strip()) if p]
    title = Employee.Title.MR
    if parts:
        key = parts[0].upper().rstrip(".")
        prefixed = parts[0].upper()
        if prefixed in TITLE_PREFIXES or key in TITLE_PREFIXES:
            title = TITLE_PREFIXES.get(prefixed) or TITLE_PREFIXES[key]
            parts = parts[1:]
    if not parts:
        return title, "UNKNOWN", "UNKNOWN"
    if len(parts) == 1:
        return title, parts[0].upper(), parts[0].upper()
    return title, parts[0].upper(), " ".join(parts[1:]).upper()


def _employee_code(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) >= 6:
        return digits[-6:]
    if digits:
        return digits.zfill(6)
    return None


def _map_grade(current_grade: str):
    raw = (current_grade or "").strip()
    upper = raw.upper()
    if upper in GRADE_MAP:
        return GRADE_MAP[upper], ""
    match = re.match(r"^(\d+)\s*([A-Z])?$", upper)
    if match:
        level = {
            "1": Student.AcademicLevel.GRADE_1,
            "2": Student.AcademicLevel.GRADE_2,
            "3": Student.AcademicLevel.GRADE_3,
            "4": Student.AcademicLevel.GRADE_4,
            "5": Student.AcademicLevel.GRADE_5,
            "6": Student.AcademicLevel.GRADE_6,
            "7": Student.AcademicLevel.GRADE_7,
            "8": Student.AcademicLevel.GRADE_8,
            "9": Student.AcademicLevel.GRADE_9,
        }.get(match.group(1))
        if level:
            return level, (match.group(2) or "").strip()
    return Student.AcademicLevel.OTHER, raw[:50]


def _map_gender(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value.startswith("f"):
        return Student.Gender.FEMALE
    if value.startswith("m"):
        return Student.Gender.MALE
    return Student.Gender.OTHER


class Command(BaseCommand):
    help = "Import legacy educentic.employees (and optionally students) into Django tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=DEFAULT_PASSWORD,
            help=f"Temporary login password for imported employees (default: {DEFAULT_PASSWORD})",
        )
        parser.add_argument(
            "--with-students",
            action="store_true",
            help="Also import legacy students into admissions_student.",
        )
        parser.add_argument(
            "--with-curriculum",
            action="store_true",
            help="Import academic levels, classes, subjects, years, terms, and school profile.",
        )
        parser.add_argument(
            "--curriculum-only",
            action="store_true",
            help="Skip employees/students; only import curriculum + school profile.",
        )
        parser.add_argument(
            "--with-assessments",
            action="store_true",
            help="Import legacy exams, sittings, and marks.",
        )
        parser.add_argument(
            "--assessments-only",
            action="store_true",
            help="Skip employees/students/curriculum; only import assessments.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Clear Django employee rows before import.",
        )

    def handle(self, *args, **options):
        password = options["password"]
        with_students = options["with_students"]
        with_curriculum = options["with_curriculum"] or options["curriculum_only"]
        with_assessments = options["with_assessments"] or options["assessments_only"]
        replace = options["replace"]
        curriculum_only = options["curriculum_only"]
        assessments_only = options["assessments_only"]

        if not curriculum_only and not assessments_only:
            if not self._legacy_table_exists("employees"):
                self.stderr.write(
                    self.style.ERROR("Legacy table `employees` not found in this database.")
                )
                return

            created, updated, skipped = self._import_employees(
                password=password, replace=replace
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Employees import complete — created={created} updated={updated} skipped={skipped}"
                )
            )

            if with_students:
                if not self._legacy_table_exists("students"):
                    self.stderr.write(self.style.ERROR("Legacy table `students` not found."))
                    return
                s_created, s_skipped = self._import_students(replace=replace)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Students import complete — created={s_created} skipped={s_skipped}"
                    )
                )

        if with_curriculum:
            summary = self._import_curriculum(replace=replace)
            self.stdout.write(self.style.SUCCESS(f"Curriculum import complete — {summary}"))

        if with_assessments:
            if not self._legacy_table_exists("exams"):
                self.stderr.write(self.style.ERROR("Legacy table `exams` not found."))
                return
            summary = self._import_assessments(replace=replace)
            self.stdout.write(self.style.SUCCESS(f"Assessments import complete — {summary}"))

    def _legacy_table_exists(self, name: str) -> bool:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name = %s
                """,
                [name],
            )
            return cursor.fetchone()[0] > 0

    def _fetch_legacy_employees(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT employee_id, full_name, email, phone, role, status
                FROM employees
                ORDER BY id
                """
            )
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _import_employees(self, *, password: str, replace: bool):
        if replace:
            with transaction.atomic():
                EmployeeRole.objects.all().delete()
                Employee.objects.all().delete()
                IssuedEmploymentNumber.objects.all().delete()
            self.stdout.write("Cleared existing Django employees.")

        created = updated = skipped = 0
        used_emails = set(
            Employee.objects.values_list("email", flat=True)
        )
        used_codes = set(
            Employee.objects.values_list("employee_code", flat=True)
        )

        for row in self._fetch_legacy_employees():
            code = _employee_code(row["employee_id"])
            email = (row["email"] or "").strip().lower()
            if not code or not email:
                skipped += 1
                self.stdout.write(f"  skip incomplete row: {row}")
                continue

            role = ROLE_MAP.get((row["role"] or "employee").strip().lower(), Employee.Role.EMPLOYEE)
            status = (row["status"] or "pending approval").strip().lower()
            if status == "active":
                approval = Employee.ApprovalStatus.APPROVED
                suspended = False
            elif status == "suspended":
                approval = Employee.ApprovalStatus.APPROVED
                suspended = True
            elif status in {"fired", "retired"}:
                approval = Employee.ApprovalStatus.REJECTED
                suspended = False
            else:
                approval = Employee.ApprovalStatus.PENDING_APPROVAL
                suspended = False

            title, first_name, last_name = _parse_name(row["full_name"])
            phone = _normalize_phone(row["phone"])

            existing = Employee.objects.filter(employee_code=code).first()
            if existing is None and email in used_emails:
                # Keep a unique email when legacy duplicates appear.
                local, _, domain = email.partition("@")
                email = f"{local}+{code}@{domain}" if domain else f"{code}@imported.local"

            try:
                with transaction.atomic():
                    if existing:
                        existing.email = email
                        existing.phone_number = phone
                        existing.title = title
                        existing.first_name = first_name
                        existing.last_name = last_name
                        existing.approval_status = approval
                        existing.is_suspended = suspended
                        existing.role = role
                        existing.set_password(password)
                        existing.save()
                        existing.set_roles([role], primary=role)
                        updated += 1
                    else:
                        if code in used_codes:
                            skipped += 1
                            continue
                        emp = Employee(
                            employee_code=code,
                            email=email,
                            phone_number=phone,
                            title=title,
                            first_name=first_name,
                            last_name=last_name,
                            approval_status=approval,
                            is_suspended=suspended,
                            role=role,
                        )
                        emp.set_password(password)
                        # employment_number claimed in save()
                        emp._allow_reassigned_employment_number = True
                        emp.save()
                        emp.set_roles([role], primary=role)
                        used_codes.add(code)
                        used_emails.add(email)
                        created += 1
                        self.stdout.write(
                            f"  + {code} {emp.display_name} [{role}] {approval}"
                        )
            except Exception as exc:  # noqa: BLE001 — continue importing remaining rows
                skipped += 1
                self.stderr.write(f"  ! failed {code} {email}: {exc}")

        return created, updated, skipped

    def _fetch_legacy_students(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    s.student_id,
                    s.full_name,
                    s.date_of_birth,
                    s.gender,
                    s.current_grade,
                    s.previous_school,
                    s.assessment_number,
                    s.address,
                    s.medical_info,
                    s.special_needs,
                    s.student_category,
                    s.sponsor_name,
                    s.sponsor_phone,
                    s.sponsor_email,
                    s.status,
                    p.full_name AS parent_name,
                    p.phone AS parent_phone,
                    p.email AS parent_email,
                    p.relationship AS parent_relationship
                FROM students s
                LEFT JOIN parents p ON p.student_id = s.student_id
                ORDER BY s.id
                """
            )
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _import_students(self, *, replace: bool):
        if replace:
            with transaction.atomic():
                Student.objects.all().delete()
                ParentGuardian.objects.all().delete()
            self.stdout.write("Cleared existing Django students/parents.")

        created = skipped = 0
        parent_by_phone: dict[str, ParentGuardian] = {
            p.phone_number: p for p in ParentGuardian.objects.all()
        }
        used_admission = set(
            Student.objects.exclude(admission_number__isnull=True)
            .exclude(admission_number="")
            .values_list("admission_number", flat=True)
        )
        seen_students: set[str] = set()

        for row in self._fetch_legacy_students():
            student_id = (row["student_id"] or "").strip()
            if not student_id or student_id in seen_students:
                continue
            seen_students.add(student_id)

            if student_id in used_admission or Student.objects.filter(
                admission_number=student_id
            ).exists():
                skipped += 1
                continue

            title, first_name, last_name = _parse_name(row["full_name"])
            # Student model has no title; reuse parse for name split only.
            del title
            level, class_group = _map_grade(row["current_grade"] or "")
            dob = row["date_of_birth"] or date(2012, 1, 1)
            gender = _map_gender(row["gender"])

            parent_phone = _normalize_phone(row["parent_phone"] or f"700{student_id[-6:].zfill(6)}")
            parent = parent_by_phone.get(parent_phone)
            if parent is None:
                parent_name = (row["parent_name"] or f"Parent of {first_name}").strip()
                parent = ParentGuardian(
                    full_name=parent_name[:200],
                    relationship_to_student=(row["parent_relationship"] or "Guardian")[:80],
                    phone_number=parent_phone,
                    email=(row["parent_email"] or "").strip()[:254],
                    is_active=True,
                )
                parent.set_password(DEFAULT_PASSWORD)
                # Ensure unique phone if collision after normalize
                suffix = 0
                while ParentGuardian.objects.filter(phone_number=parent.phone_number).exists():
                    suffix += 1
                    parent.phone_number = f"{parent_phone[:-1]}{suffix}"[:24]
                parent.save()
                parent_by_phone[parent.phone_number] = parent

            sponsor = Student.SponsorshipCategory.SELF
            category = (row["student_category"] or "").strip().lower()
            if "gov" in category:
                sponsor = Student.SponsorshipCategory.GOVERNMENT
            elif "both" in category:
                sponsor = Student.SponsorshipCategory.BOTH

            enrollment = Student.EnrollmentStatus.ACTIVE
            status = (row["status"] or "").strip().lower()
            if status in {"transferred", "transfer"}:
                enrollment = Student.EnrollmentStatus.TRANSFER
            elif status in {"alumni", "alumnae"}:
                enrollment = Student.EnrollmentStatus.ALUMNAE

            assessment = (row["assessment_number"] or "").strip() or None
            if assessment and Student.objects.filter(assessment_number=assessment).exists():
                assessment = None

            try:
                with transaction.atomic():
                    student = Student(
                        first_name=first_name[:150],
                        middle_name="",
                        last_name=last_name[:150],
                        date_of_birth=dob,
                        gender=gender,
                        academic_level=level,
                        admission_number=student_id[:40],
                        class_group=class_group[:50],
                        assessment_number=assessment,
                        previous_school=(row["previous_school"] or "")[:200],
                        sponsorship_category=sponsor,
                        sponsor_details=(row["sponsor_name"] or ""),
                        parent_guardian=parent,
                        home_address=row["address"] or "",
                        medical_notes=row["medical_info"] or "",
                        special_needs=row["special_needs"] or "",
                        emergency_contact="",
                        is_suspended=status == "suspended",
                        enrollment_status=enrollment,
                        is_active=status == "in session",
                    )
                    student.set_password(DEFAULT_PASSWORD)
                    student.save()
                    used_admission.add(student_id)
                    created += 1
                    if created % 50 == 0:
                        self.stdout.write(f"  … {created} students", ending="\n")
                        self.stdout.flush()
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                self.stderr.write(f"  ! student {student_id}: {exc}")
                self.stderr.flush()

        return created, skipped

    def _grade_key_from_level_name(self, level_name: str):
        raw = (level_name or "").strip().upper()
        if raw.startswith("GRADE"):
            match = re.search(r"GRADE\s*(\d+)", raw)
            if match:
                num = int(match.group(1))
                return f"GRADE {num}", num, ""
        match = re.match(r"^(\d+)\s*([A-Z])?$", raw)
        if match:
            num = int(match.group(1))
            stream = (match.group(2) or "").strip()
            return f"GRADE {num}", num, stream
        return raw, 100, ""

    def _import_curriculum(self, *, replace: bool):
        if replace:
            with transaction.atomic():
                LearningArea.objects.all().delete()
                AcademicClass.objects.all().delete()
                AcademicTerm.objects.all().delete()
                AcademicYear.objects.all().delete()
                AcademicLevel.objects.all().delete()
            self.stdout.write("Cleared existing Django curriculum rows.")

        level_by_legacy_id = {}
        class_by_legacy_id = {}
        levels_created = classes_created = 0

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, level_category, level_name, level_code, level_description, level_status
                FROM academic_levels
                ORDER BY id
                """
            )
            legacy_levels = cursor.fetchall()

        grade_levels: dict[str, AcademicLevel] = {
            lvl.name.upper(): lvl for lvl in AcademicLevel.objects.all()
        }

        for legacy_id, category, level_name, level_code, description, status in legacy_levels:
            grade_name, order, stream = self._grade_key_from_level_name(level_name)
            grade_key = grade_name.upper()
            level = grade_levels.get(grade_key)
            if level is None:
                code_base = re.sub(r"[^A-Z0-9]+", "-", grade_key).strip("-") or f"LVL-{legacy_id}"
                code = code_base[:40]
                suffix = 1
                while AcademicLevel.objects.filter(code=code).exists():
                    suffix += 1
                    code = f"{code_base[:36]}-{suffix}"
                level = AcademicLevel.objects.create(
                    name=grade_name[:120],
                    code=code,
                    category=(category or "GENERAL")[:120],
                    description=description or "",
                    order=order,
                    status=(
                        AcademicLevel.Status.ACTIVE
                        if (status or "active").lower() == "active"
                        else AcademicLevel.Status.INACTIVE
                    ),
                )
                grade_levels[grade_key] = level
                levels_created += 1
                self.stdout.write(f"  + level {level.name}")

            level_by_legacy_id[legacy_id] = level

            class_name = (level_name or grade_name).strip()[:120]
            class_code = (level_name or level_code or f"C{legacy_id}").strip()[:40]
            academic_class, created = AcademicClass.objects.get_or_create(
                academic_level=level,
                code=class_code,
                defaults={
                    "name": class_name,
                    "order": order * 10 + (ord(stream) - 64 if stream else 0),
                    "status": (
                        AcademicClass.Status.ACTIVE
                        if (status or "active").lower() == "active"
                        else AcademicClass.Status.INACTIVE
                    ),
                },
            )
            if created:
                classes_created += 1
            class_by_legacy_id[legacy_id] = academic_class

        # Class teachers
        teachers_linked = 0
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT cta.academic_level_id, e.employee_id
                FROM class_teacher_assignments cta
                JOIN employees e ON e.id = cta.teacher_id
                """
            )
            for legacy_level_id, employee_code in cursor.fetchall():
                academic_class = class_by_legacy_id.get(legacy_level_id)
                code = _employee_code(employee_code)
                if not academic_class or not code:
                    continue
                teacher = Employee.objects.filter(employee_code=code).first()
                if not teacher:
                    continue
                if academic_class.class_teacher_id != teacher.id:
                    academic_class.class_teacher = teacher
                    academic_class.save(update_fields=["class_teacher", "updated_at"])
                    teachers_linked += 1

        # Subjects / learning areas
        subjects_created = 0
        subject_by_legacy_id = {}
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, subject_name, subject_code, description, status,
                       exam_total_marks, exam_display_order
                FROM subjects
                ORDER BY id
                """
            )
            legacy_subjects = cursor.fetchall()

        for (
            sid,
            subject_name,
            subject_code,
            description,
            status,
            total_marks,
            display_order,
        ) in legacy_subjects:
            code = (subject_code or f"SUB-{sid}").strip()[:40]
            area = LearningArea.objects.filter(code=code).first()
            if area is None:
                area = LearningArea.objects.create(
                    name=(subject_name or code)[:120],
                    code=code,
                    description=description or "",
                    total_marks=int(total_marks or 100),
                    display_order=int(display_order or 0),
                    status=(
                        LearningArea.Status.ACTIVE
                        if (status or "active").lower() == "active"
                        else LearningArea.Status.INACTIVE
                    ),
                )
                subjects_created += 1
                self.stdout.write(f"  + subject {area.name}")
            subject_by_legacy_id[sid] = area

        links = 0
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT subject_id, academic_level_id FROM subject_academic_levels"
            )
            for subject_id, legacy_level_id in cursor.fetchall():
                area = subject_by_legacy_id.get(subject_id)
                level = level_by_legacy_id.get(legacy_level_id)
                if area and level:
                    area.academic_levels.add(level)
                    links += 1

        # Academic years + terms
        years_created = terms_created = 0
        year_by_legacy_id = {}
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, year_name, start_date, end_date, status, is_current
                FROM academic_years
                ORDER BY id
                """
            )
            for yid, year_name, start_date, end_date, status, is_current in cursor.fetchall():
                name = (year_name or AcademicYear.name_from_dates(start_date, end_date))[:40]
                year = AcademicYear.objects.filter(name=name).first()
                if year is None:
                    year = AcademicYear(
                        name=name,
                        start_date=start_date,
                        end_date=end_date,
                        is_current=bool(is_current),
                        status=(
                            AcademicYear.Status.ACTIVE
                            if (status or "").lower() in {"active", "draft"}
                            else AcademicYear.Status.INACTIVE
                        ),
                    )
                    year.save()
                    years_created += 1
                else:
                    year.start_date = start_date
                    year.end_date = end_date
                    year.is_current = bool(is_current)
                    year.save(update_fields=["start_date", "end_date", "is_current", "updated_at"])
                year_by_legacy_id[yid] = year

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, term_name, academic_year_id, start_date, end_date, is_current
                FROM terms
                ORDER BY id
                """
            )
            for tid, term_name, year_id, start_date, end_date, is_current in cursor.fetchall():
                year = year_by_legacy_id.get(year_id)
                if not year:
                    continue
                name = (term_name or f"Term {tid}")[:80]
                order = 0
                m = re.search(r"(\d+)", name)
                if m:
                    order = int(m.group(1))
                midterm = start_date + timedelta(
                    days=max(0, (end_date - start_date).days // 2)
                )
                term, created = AcademicTerm.objects.get_or_create(
                    academic_year=year,
                    name=name,
                    defaults={
                        "start_date": start_date,
                        "end_date": end_date,
                        "opening_date": start_date,
                        "midterm_date": midterm,
                        "closing_date": end_date,
                        "order": order,
                        "is_current": bool(is_current),
                    },
                )
                if created:
                    terms_created += 1
                elif bool(is_current) and not term.is_current:
                    term.is_current = True
                    term.save(update_fields=["is_current", "updated_at"])

        # School profile
        profile_note = "unchanged"
        if self._legacy_table_exists("school_settings"):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT school_name, school_email, school_phone, school_location,
                           about_mission, about_vision, primary_color, project_name
                    FROM school_settings
                    ORDER BY id
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
            if row:
                (
                    school_name,
                    school_email,
                    school_phone,
                    school_location,
                    about_mission,
                    about_vision,
                    primary_color,
                    project_name,
                ) = row
                profile = SchoolProfile.objects.first()
                payload = {
                    "official_name": (school_name or "School")[:255],
                    "display_name": (school_name or project_name or "School")[:120],
                    "school_type": SchoolProfile.SchoolType.PRIMARY,
                    "ownership": SchoolProfile.Ownership.PUBLIC,
                    "physical_address": school_location or "",
                    "main_phone": (school_phone or "")[:24],
                    "general_email": school_email or "",
                    "mission_statement": about_mission or "",
                    "vision_statement": about_vision or "",
                    "primary_color": (primary_color or "")[:7],
                }
                if profile is None:
                    SchoolProfile.objects.create(**payload)
                    profile_note = "created"
                else:
                    for key, value in payload.items():
                        setattr(profile, key, value)
                    profile.save()
                    profile_note = "updated"

        return (
            f"levels={levels_created} classes={classes_created} "
            f"teachers_linked={teachers_linked} subjects={subjects_created} "
            f"subject_links={links} years={years_created} terms={terms_created} "
            f"school_profile={profile_note}"
        )

    def _rebuild_legacy_maps(self):
        """Rebuild legacy-id → Django object maps from current DB state."""
        class_by_legacy_id = {}
        level_by_legacy_id = {}
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, level_name FROM academic_levels")
            for legacy_id, level_name in cursor.fetchall():
                name = (level_name or "").strip()
                academic_class = (
                    AcademicClass.objects.filter(code__iexact=name).first()
                    or AcademicClass.objects.filter(name__iexact=name).first()
                )
                if academic_class:
                    class_by_legacy_id[legacy_id] = academic_class
                    level_by_legacy_id[legacy_id] = academic_class.academic_level

        subject_by_legacy_id = {}
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, subject_code FROM subjects")
            for sid, subject_code in cursor.fetchall():
                code = (subject_code or "").strip()
                area = LearningArea.objects.filter(code=code).first()
                if area:
                    subject_by_legacy_id[sid] = area

        year_by_legacy_id = {}
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, year_name FROM academic_years")
            for yid, year_name in cursor.fetchall():
                year = AcademicYear.objects.filter(name=(year_name or "").strip()[:40]).first()
                if year:
                    year_by_legacy_id[yid] = year

        term_by_legacy_id = {}
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, term_name, academic_year_id FROM terms"
            )
            for tid, term_name, year_id in cursor.fetchall():
                year = year_by_legacy_id.get(year_id)
                if not year:
                    continue
                term = AcademicTerm.objects.filter(
                    academic_year=year, name=(term_name or "").strip()[:80]
                ).first()
                if term:
                    term_by_legacy_id[tid] = term

        employee_by_legacy_id = {}
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, employee_id FROM employees")
            for eid, employee_code in cursor.fetchall():
                code = _employee_code(employee_code)
                if not code:
                    continue
                emp = Employee.objects.filter(employee_code=code).first()
                if emp:
                    employee_by_legacy_id[eid] = emp

        student_by_admission = {
            s.admission_number: s
            for s in Student.objects.exclude(admission_number__isnull=True).exclude(
                admission_number=""
            )
        }

        return {
            "class_by_legacy_id": class_by_legacy_id,
            "level_by_legacy_id": level_by_legacy_id,
            "subject_by_legacy_id": subject_by_legacy_id,
            "year_by_legacy_id": year_by_legacy_id,
            "term_by_legacy_id": term_by_legacy_id,
            "employee_by_legacy_id": employee_by_legacy_id,
            "student_by_admission": student_by_admission,
        }

    def _map_exam_status(self, status: str) -> str:
        value = (status or "").strip().lower()
        if value in {"submitted", "gazetted", "completed"}:
            return GeneratedExamTimetable.Status.PUBLISHED
        if value == "ongoing":
            return GeneratedExamTimetable.Status.IN_SESSION
        if value == "cancelled":
            return GeneratedExamTimetable.Status.SCHEDULED
        return GeneratedExamTimetable.Status.SCHEDULED

    def _import_assessments(self, *, replace: bool):
        if replace:
            with transaction.atomic():
                ExamMark.objects.all().delete()
                GeneratedExamSitting.objects.all().delete()
                GeneratedExamTimetable.objects.all().delete()
            self.stdout.write("Cleared existing Django assessments.")

        maps = self._rebuild_legacy_maps()
        class_by_legacy_id = maps["class_by_legacy_id"]
        level_by_legacy_id = maps["level_by_legacy_id"]
        subject_by_legacy_id = maps["subject_by_legacy_id"]
        year_by_legacy_id = maps["year_by_legacy_id"]
        term_by_legacy_id = maps["term_by_legacy_id"]
        employee_by_legacy_id = maps["employee_by_legacy_id"]
        student_by_admission = maps["student_by_admission"]

        current_exam_name = ""
        if self._legacy_table_exists("school_settings"):
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT registered_current_exam_json FROM school_settings ORDER BY id LIMIT 1"
                )
                row = cursor.fetchone()
            if row and row[0]:
                raw = row[0]
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", errors="ignore")
                match = re.search(r'"exam_name"\s*:\s*"([^"]+)"', str(raw))
                if match:
                    current_exam_name = match.group(1).strip().upper()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    exam_name,
                    exam_type,
                    academic_year_id,
                    term_id,
                    MIN(exam_date) AS start_date,
                    MAX(exam_date) AS end_date,
                    MAX(status) AS status
                FROM exams
                GROUP BY exam_name, exam_type, academic_year_id, term_id
                ORDER BY MIN(exam_date)
                """
            )
            exam_groups = cursor.fetchall()

        generation_by_name = {}
        generations_created = 0
        for exam_name, exam_type, year_id, term_id, start_date, end_date, status in exam_groups:
            name = (exam_name or "").strip().upper()[:120]
            year = year_by_legacy_id.get(year_id)
            term = term_by_legacy_id.get(term_id)
            if not name or not year or not term:
                self.stderr.write(f"  ! skip assessment group {exam_name}: missing year/term")
                continue

            generation = GeneratedExamTimetable.objects.filter(name=name).first()
            is_current = bool(current_exam_name) and name == current_exam_name.upper()
            if generation is None:
                generation = GeneratedExamTimetable(
                    name=name,
                    academic_year=year,
                    academic_term=term,
                    start_date=start_date,
                    end_date=end_date,
                    status=self._map_exam_status(status),
                    is_current=is_current,
                )
                generation.save()
                generations_created += 1
                self.stdout.write(f"  + assessment {generation.name}")
            else:
                generation.academic_year = year
                generation.academic_term = term
                generation.start_date = start_date
                generation.end_date = end_date
                generation.status = self._map_exam_status(status)
                generation.is_current = is_current
                generation.save()

            generation_by_name[name] = generation

        # Attach academic levels used by each assessment
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT exam_name, academic_level_id
                FROM exams
                """
            )
            for exam_name, legacy_level_id in cursor.fetchall():
                generation = generation_by_name.get((exam_name or "").strip().upper()[:120])
                level = level_by_legacy_id.get(legacy_level_id)
                if generation and level:
                    generation.academic_levels.add(level)

        # Sittings
        sittings_created = 0
        exam_id_to_generation = {}
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id, exam_name, academic_level_id, subject_id, exam_date,
                    start_time, end_time, session_type, supervisor_id
                FROM exams
                ORDER BY id
                """
            )
            exam_rows = cursor.fetchall()

        weekday_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        default_start = time(8, 0)
        default_end = time(10, 0)

        sitting_bulk = []
        for (
            exam_id,
            exam_name,
            legacy_level_id,
            subject_id,
            exam_date,
            start_time,
            end_time,
            session_type,
            supervisor_id,
        ) in exam_rows:
            generation = generation_by_name.get((exam_name or "").strip().upper()[:120])
            academic_class = class_by_legacy_id.get(legacy_level_id)
            level = level_by_legacy_id.get(legacy_level_id)
            learning_area = subject_by_legacy_id.get(subject_id)
            if not generation or not academic_class or not level or not learning_area:
                continue

            exam_id_to_generation[exam_id] = generation
            supervisor = employee_by_legacy_id.get(supervisor_id)
            weekday = weekday_names[exam_date.weekday()] if exam_date else "MON"
            period_name = (session_type or "SESSION").strip().upper()[:120] or "SESSION"
            sitting_bulk.append(
                GeneratedExamSitting(
                    generation=generation,
                    academic_level=level,
                    academic_class=academic_class,
                    learning_area=learning_area,
                    supervisor=supervisor,
                    weekday=weekday,
                    exam_date=exam_date,
                    period_name=period_name,
                    start_time=start_time or default_start,
                    end_time=end_time or default_end,
                )
            )

        if sitting_bulk:
            # Avoid duplicates on re-run for the same generation
            existing_keys = set(
                GeneratedExamSitting.objects.filter(
                    generation_id__in=[g.id for g in generation_by_name.values()]
                ).values_list(
                    "generation_id",
                    "academic_class_id",
                    "learning_area_id",
                    "exam_date",
                    "start_time",
                )
            )
            to_create = []
            for sitting in sitting_bulk:
                key = (
                    sitting.generation_id,
                    sitting.academic_class_id,
                    sitting.learning_area_id,
                    sitting.exam_date,
                    sitting.start_time,
                )
                if key in existing_keys:
                    continue
                to_create.append(sitting)
                existing_keys.add(key)
            GeneratedExamSitting.objects.bulk_create(to_create, batch_size=500)
            sittings_created = len(to_create)

        # Marks
        marks_created = 0
        marks_skipped = 0
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT student_id, subject_id, exam_id, marks
                FROM student_marks
                ORDER BY id
                """
            )
            mark_rows = cursor.fetchall()

        # Keep last mark when duplicates exist for same generation/student/subject
        mark_map = {}
        for student_id, subject_id, exam_id, marks in mark_rows:
            generation = exam_id_to_generation.get(exam_id)
            student = student_by_admission.get(str(student_id))
            learning_area = subject_by_legacy_id.get(subject_id)
            if not generation or not student or not learning_area:
                marks_skipped += 1
                continue
            if marks is None:
                marks_skipped += 1
                continue
            try:
                score = int(Decimal(str(marks)))
            except Exception:  # noqa: BLE001
                marks_skipped += 1
                continue
            score = max(0, score)
            out_of = learning_area.total_marks or 100
            mark_map[(generation.id, student.id, learning_area.id)] = (
                generation,
                student,
                learning_area,
                score,
                out_of,
            )

        existing_mark_keys = set(
            ExamMark.objects.filter(
                generation_id__in=[g.id for g in generation_by_name.values()]
            ).values_list("generation_id", "student_id", "learning_area_id")
        )
        mark_bulk = []
        for key, (generation, student, learning_area, score, out_of) in mark_map.items():
            if key in existing_mark_keys:
                continue
            mark_bulk.append(
                ExamMark(
                    generation=generation,
                    student=student,
                    learning_area=learning_area,
                    marks=score,
                    out_of_marks=out_of,
                )
            )
        if mark_bulk:
            ExamMark.objects.bulk_create(mark_bulk, batch_size=1000)
            marks_created = len(mark_bulk)

        return (
            f"assessments={generations_created} sittings={sittings_created} "
            f"marks={marks_created} marks_skipped={marks_skipped}"
        )
