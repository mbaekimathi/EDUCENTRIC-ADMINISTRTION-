"""
FULL demo showcase for Best Kenya College.

WARNING: Intended for empty/demo databases only. Do NOT run on a live school DB.
Requires an explicit --confirm-demo flag.

Creates (on top of seed_best_kenya_college):
  - Pending employee approvals
  - Cleared / alumnae students
  - Learning + e-learning timetables
  - Exam timetable + published results (ExamMark)
  - Class attendance sessions

Usage:
  python manage.py seed_best_kenya_college_full --confirm-demo
  python manage.py seed_best_kenya_college_full --confirm-demo --password DemoPass123!
"""

from __future__ import annotations

from datetime import date, time, timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.admissions.models import ParentGuardian, Student
from apps.curriculum.models import (
    AcademicClass,
    AcademicLevel,
    AcademicTerm,
    AcademicYear,
    ClassAttendanceRecord,
    ClassAttendanceSession,
    ClassSubjectAllocation,
    ELearningSubjectAllocation,
    ExamMark,
    ExamSubjectSetting,
    GeneratedELearningLesson,
    GeneratedELearningTimetable,
    GeneratedExamTimetable,
    GeneratedLearningLesson,
    GeneratedLearningTimetable,
    LearningArea,
    LearningScheduleActivity,
    LearningScheduleProfile,
)
from apps.employees.models import Employee

DEFAULT_PASSWORD = "DemoPass123!"

PENDING_EMPLOYEES = [
    ("100011", "MR", "Allan", "Kariuki", "TEACHER", "allan.kariuki@bestkenyacollege.ac.ke", "+254712000011"),
    ("100012", "MS", "Beatrice", "Wambui", "TEACHER", "beatrice.wambui@bestkenyacollege.ac.ke", "+254712000012"),
    ("100013", "MR", "Caleb", "Njoroge", "SECRETARY", "caleb.njoroge@bestkenyacollege.ac.ke", "+254712000013"),
]

CLEARED_STUDENTS = [
    # assessment, status, reason, first, middle, last, gender, dob, adm, parent phone suffix
    ("ASM1091", Student.EnrollmentStatus.ALUMNAE, Student.ClearanceReason.COMPLETED_SCHOOL,
     "Oliver", "K", "Maina", "MALE", date(2000, 4, 2), "BKC/2024/091", "091"),
    ("ASM1092", Student.EnrollmentStatus.TRANSFER, Student.ClearanceReason.TRANSFER,
     "Patricia", "", "Wairimu", "FEMALE", date(2001, 9, 15), "BKC/2025/092", "092"),
]


class Command(BaseCommand):
    help = (
        "FULL Best Kenya College demo: base seed + pending approvals, cleared "
        "students, timetables, exam results, attendance. DEMO DATABASES ONLY."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm-demo",
            action="store_true",
            help="Required. Confirms this is a demo DB (not a live school).",
        )
        parser.add_argument(
            "--password",
            default=DEFAULT_PASSWORD,
            help=f"Shared demo password (default: {DEFAULT_PASSWORD})",
        )
        parser.add_argument(
            "--skip-base",
            action="store_true",
            help="Skip seed_best_kenya_college (assume already run).",
        )

    def handle(self, *args, **options):
        if not options["confirm_demo"]:
            raise CommandError(
                "Refusing to run. This command overwrites/adds large demo datasets.\n"
                "Only use on empty/demo MySQL — never on a live school.\n"
                "Re-run with: python manage.py seed_best_kenya_college_full --confirm-demo"
            )

        password = options["password"]
        if not options["skip_base"]:
            self.stdout.write("Running base college seed…")
            call_command(
                "seed_best_kenya_college",
                password=password,
                reset_passwords=True,
                verbosity=options.get("verbosity", 1),
            )

        with transaction.atomic():
            pending = self._seed_pending_employees(password)
            cleared = self._seed_cleared_students(password)
            levels = list(
                AcademicLevel.objects.filter(status=AcademicLevel.Status.ACTIVE).order_by("order")
            )
            classes = list(
                AcademicClass.objects.filter(status=AcademicClass.Status.ACTIVE)
                .select_related("academic_level")
                .order_by("academic_level__order", "order")
            )
            subjects = list(
                LearningArea.objects.filter(status=LearningArea.Status.ACTIVE).order_by(
                    "display_order"
                )
            )
            teachers = list(
                Employee.objects.filter(
                    approval_status=Employee.ApprovalStatus.APPROVED,
                    assigned_roles__role=Employee.Role.TEACHER,
                ).distinct()
            )
            head = Employee.objects.filter(employee_code="100001").first()
            year = AcademicYear.objects.filter(name="2026").first()
            term = AcademicTerm.objects.filter(
                academic_year=year, name="Semester 1"
            ).first() if year else None

            learn_lessons = self._seed_learning_timetable(levels, classes, subjects, teachers, head)
            elearn_lessons = self._seed_elearning_timetable(levels, subjects, teachers, head)
            marks = self._seed_exam_results(levels, subjects, year, term, head)
            attendance = self._seed_attendance(classes, teachers)

        self.stdout.write(self.style.SUCCESS("FULL Best Kenya College showcase ready."))
        self.stdout.write(f"  Pending approvals: {pending}")
        self.stdout.write(f"  Cleared students:  {cleared}")
        self.stdout.write(f"  Learning lessons:  {learn_lessons}")
        self.stdout.write(f"  E-learning lessons:{elearn_lessons}")
        self.stdout.write(f"  Exam marks:        {marks}")
        self.stdout.write(f"  Attendance days:   {attendance}")
        self.stdout.write("")
        self.stdout.write("Next (ACCOUNTS):")
        self.stdout.write(
            "  python manage.py seed_demo_fees --full --confirm-demo"
        )

    def _seed_pending_employees(self, password):
        n = 0
        for code, title, first, last, role, email, phone in PENDING_EMPLOYEES:
            emp = Employee.objects.filter(employee_code=code).first()
            if emp is None:
                emp = Employee.objects.create_user(
                    employee_code=code,
                    password=password,
                    email=email,
                    title=title,
                    first_name=first,
                    last_name=last,
                    phone_number=phone,
                    role=role,
                    approval_status=Employee.ApprovalStatus.PENDING_APPROVAL,
                )
                n += 1
            else:
                emp.approval_status = Employee.ApprovalStatus.PENDING_APPROVAL
                emp.is_suspended = False
                emp.save()
            emp.set_roles([role], primary=role)
        self.stdout.write(self.style.SUCCESS(f"Pending employees: {len(PENDING_EMPLOYEES)} ({n} new)"))
        return len(PENDING_EMPLOYEES)

    def _seed_cleared_students(self, password):
        n = 0
        for assess, status, reason, first, middle, last, gender, dob, adm, phone_sfx in CLEARED_STUDENTS:
            phone = f"+254722100{phone_sfx}"
            parent = ParentGuardian.objects.filter(phone_number=phone).first()
            if parent is None:
                parent = ParentGuardian(
                    full_name=f"Guardian of {first} {last}",
                    relationship_to_student="GUARDIAN",
                    phone_number=phone,
                    email=f"guardian{phone_sfx}@example.com",
                    is_active=True,
                )
                parent.set_password(password)
                parent.save()

            student = Student.objects.filter(assessment_number=assess).first()
            if student is None:
                student = Student(
                    first_name=first,
                    middle_name=middle,
                    last_name=last,
                    date_of_birth=dob,
                    gender=gender,
                    academic_level=Student.AcademicLevel.YEAR_4,
                    admission_number=adm,
                    assessment_number=assess,
                    class_group="Fourth Year — Business Management",
                    sponsorship_category=Student.SponsorshipCategory.SELF,
                    parent_guardian=parent,
                    home_address="Nairobi, Kenya",
                    enrollment_status=status,
                    clearance_reason=reason,
                    cleared_at=timezone.now() - timedelta(days=30),
                    is_active=False,
                    is_suspended=False,
                    previous_school="County Secondary School",
                )
                student.set_password(password)
                student.save()
                n += 1
            else:
                student.enrollment_status = status
                student.clearance_reason = reason
                student.cleared_at = timezone.now() - timedelta(days=30)
                student.is_active = False
                student.save()
        self.stdout.write(self.style.SUCCESS(f"Cleared students: {len(CLEARED_STUDENTS)} ({n} new)"))
        return len(CLEARED_STUDENTS)

    def _seed_learning_timetable(self, levels, classes, subjects, teachers, head):
        if not classes or not subjects or not teachers:
            self.stdout.write(self.style.WARNING("Skip learning timetable (missing classes/subjects/teachers)"))
            return 0

        profile, _ = LearningScheduleProfile.objects.get_or_create(
            kind=LearningScheduleProfile.Kind.LEARNING,
            name="BKC UNDERGRADUATE DAY",
            category="UNDERGRADUATE",
            defaults={
                "study_days": ["MON", "TUE", "WED", "THU", "FRI"],
                "lesson_duration_minutes": 60,
                "first_class_start_time": time(8, 0),
                "last_class_end_time": time(16, 0),
            },
        )
        profile.study_days = ["MON", "TUE", "WED", "THU", "FRI"]
        profile.lesson_duration_minutes = 60
        profile.first_class_start_time = time(8, 0)
        profile.last_class_end_time = time(16, 0)
        profile.save()
        profile.academic_levels.set(levels[:4] or levels)

        for order, (pname, start) in enumerate(
            [("Period 1", time(8, 0)), ("Period 2", time(9, 10)), ("Period 3", time(11, 0))],
            start=1,
        ):
            LearningScheduleActivity.objects.get_or_create(
                profile=profile,
                name=pname,
                defaults={"start_time": start, "duration_minutes": 60, "order": order},
            )

        # Idempotent: wipe previous BKC demo generation lessons via created_by + recent pattern
        gen = GeneratedLearningTimetable.objects.filter(created_by=head).order_by("-created_at").first()
        if gen is None:
            gen = GeneratedLearningTimetable.objects.create(created_by=head)
        else:
            gen.lessons.all().delete()
        gen.academic_levels.set(levels[:4] or levels)

        weekdays = ["MON", "TUE", "WED", "THU", "FRI"]
        periods = [
            ("Period 1", time(8, 0), time(9, 0)),
            ("Period 2", time(9, 10), time(10, 10)),
            ("Period 3", time(11, 0), time(12, 0)),
        ]
        created = 0
        for i, klass in enumerate(classes[:6]):
            allocs = list(
                ClassSubjectAllocation.objects.filter(academic_class=klass).select_related(
                    "learning_area", "teacher"
                )[:5]
            )
            if not allocs:
                continue
            for d, day in enumerate(weekdays):
                alloc = allocs[d % len(allocs)]
                pname, start, end = periods[d % len(periods)]
                GeneratedLearningLesson.objects.create(
                    generation=gen,
                    academic_level=klass.academic_level,
                    academic_class=klass,
                    learning_area=alloc.learning_area,
                    teacher=alloc.teacher,
                    weekday=day,
                    period_name=pname,
                    start_time=start,
                    end_time=end,
                )
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Learning timetable lessons: {created}"))
        return created

    def _seed_elearning_timetable(self, levels, subjects, teachers, head):
        if not levels or not subjects or not teachers:
            return 0

        for i, level in enumerate(levels[:5]):
            for j, area in enumerate(subjects[:4]):
                if not area.academic_levels.filter(pk=level.pk).exists():
                    continue
                ELearningSubjectAllocation.objects.get_or_create(
                    academic_level=level,
                    learning_area=area,
                    defaults={"teacher": teachers[j % len(teachers)]},
                )

        profile, _ = LearningScheduleProfile.objects.get_or_create(
            kind=LearningScheduleProfile.Kind.ELEARNING,
            name="BKC E-LEARNING EVENING",
            category="UNDERGRADUATE",
            defaults={
                "study_days": ["MON", "WED", "FRI"],
                "lesson_duration_minutes": 90,
                "first_class_start_time": time(18, 0),
                "last_class_end_time": time(21, 0),
            },
        )
        profile.academic_levels.set(levels[:4] or levels)

        gen = GeneratedELearningTimetable.objects.filter(created_by=head).order_by("-created_at").first()
        if gen is None:
            gen = GeneratedELearningTimetable.objects.create(created_by=head)
        else:
            gen.lessons.all().delete()
        gen.academic_levels.set(levels[:4] or levels)

        created = 0
        days = ["MON", "WED", "FRI"]
        for i, level in enumerate(levels[:4]):
            allocs = list(
                ELearningSubjectAllocation.objects.filter(academic_level=level).select_related(
                    "learning_area", "teacher"
                )[:3]
            )
            for d, day in enumerate(days):
                if not allocs:
                    break
                alloc = allocs[d % len(allocs)]
                GeneratedELearningLesson.objects.create(
                    generation=gen,
                    academic_level=level,
                    learning_area=alloc.learning_area,
                    teacher=alloc.teacher,
                    weekday=day,
                    period_name=f"Online {d + 1}",
                    start_time=time(18, 0),
                    end_time=time(19, 30),
                )
                created += 1
        self.stdout.write(self.style.SUCCESS(f"E-learning lessons: {created}"))
        return created

    def _seed_exam_results(self, levels, subjects, year, term, head):
        if year is None or term is None:
            self.stdout.write(self.style.WARNING("Skip exams (missing academic year/term)"))
            return 0

        exam, _ = GeneratedExamTimetable.objects.get_or_create(
            name="BKC SEMESTER 1 CAT 2026",
            defaults={
                "created_by": head,
                "academic_year": year,
                "academic_term": term,
                "start_date": date(2026, 2, 10),
                "end_date": date(2026, 2, 20),
                "status": GeneratedExamTimetable.Status.PUBLISHED,
                "is_current": True,
                "deadline": timezone.now() + timedelta(days=20),
            },
        )
        exam.academic_year = year
        exam.academic_term = term
        exam.status = GeneratedExamTimetable.Status.PUBLISHED
        exam.is_current = True
        exam.start_date = date(2026, 2, 10)
        exam.end_date = date(2026, 2, 20)
        exam.save()
        exam.academic_levels.set(levels[:6] or levels)

        active_students = list(
            Student.objects.filter(
                assessment_number__in=[f"ASM{1001 + i}" for i in range(10)],
                enrollment_status=Student.EnrollmentStatus.ACTIVE,
            )
        )
        created = 0
        for student in active_students:
            # Match subjects linked to any level; prefer settings for student's mapped levels
            settings = list(ExamSubjectSetting.objects.select_related("learning_area")[:6])
            for idx, setting in enumerate(settings):
                marks = 45 + ((student.pk + idx * 7) % 50)
                out_of = setting.out_of_marks or 100
                marks = min(marks, out_of)
                _, made = ExamMark.objects.update_or_create(
                    generation=exam,
                    student=student,
                    learning_area=setting.learning_area,
                    defaults={"marks": marks, "out_of_marks": out_of},
                )
                if made:
                    created += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Exam marks upserted for {len(active_students)} students "
                f"({created} new rows)"
            )
        )
        return created or ExamMark.objects.filter(generation=exam).count()

    def _seed_attendance(self, classes, teachers):
        if not classes:
            return 0
        days = 0
        today = date.today()
        for offset in range(5):
            day = today - timedelta(days=offset)
            if day.weekday() >= 5:  # skip weekend
                continue
            for klass in classes[:5]:
                teacher = teachers[days % len(teachers)] if teachers else None
                session, _ = ClassAttendanceSession.objects.get_or_create(
                    academic_class=klass,
                    attendance_date=day,
                    defaults={
                        "taken_by": teacher,
                        "notes": "BKC demo attendance",
                    },
                )
                # Students loosely matching this class_group / level
                learners = Student.objects.filter(
                    enrollment_status=Student.EnrollmentStatus.ACTIVE,
                    is_active=True,
                )[:10]
                for s in learners:
                    ClassAttendanceRecord.objects.get_or_create(
                        session=session,
                        student=s,
                        defaults={
                            "morning": True,
                            "afternoon": (s.pk + offset) % 3 != 0,
                            "evening": False,
                        },
                    )
                days += 1
        self.stdout.write(self.style.SUCCESS(f"Attendance sessions seeded (~{days})"))
        return days
