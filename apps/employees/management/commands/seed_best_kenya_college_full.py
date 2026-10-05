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

from apps.admissions.models import AdmissionSettings, ParentGuardian, Student
from apps.curriculum.models import (
    AcademicClass,
    AcademicLevel,
    AcademicTerm,
    AcademicYear,
    ClassAttendanceRecord,
    ClassAttendanceSession,
    ClassSubjectAllocation,
    ClassSubjectLessonPlan,
    ELearningAttendanceRecord,
    ELearningAttendanceSession,
    ELearningSubjectAllocation,
    ExamMark,
    ExamScheduleActivity,
    ExamScheduleProfile,
    ExamSubjectSetting,
    ExamSupervisorAllocation,
    ExamTimetableSession,
    GeneratedELearningLesson,
    GeneratedELearningTimetable,
    GeneratedExamSitting,
    GeneratedExamTimetable,
    GeneratedLearningLesson,
    GeneratedLearningTimetable,
    GradeBand,
    LearningArea,
    LearningScheduleActivity,
    LearningScheduleProfile,
)
from apps.employees.models import (
    Employee,
    SchoolActivity,
    SchoolActivityDay,
    SchoolProfile,
    StudentConductRecord,
)

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
            bands = self._seed_grade_bands(levels)
            sittings = self._seed_exam_sittings_and_supervisors(classes, subjects, teachers, head)
            conduct = self._seed_conduct_and_activities(levels, head)
            plans = self._seed_lesson_plans(teachers)
            elearn_att = self._seed_elearning_attendance(teachers)
            self._enrich_school_and_admissions()

        self.stdout.write(self.style.SUCCESS("FULL Best Kenya College showcase ready."))
        self.stdout.write(f"  Pending approvals: {pending}")
        self.stdout.write(f"  Cleared students:  {cleared}")
        self.stdout.write(f"  Learning lessons:  {learn_lessons}")
        self.stdout.write(f"  E-learning lessons:{elearn_lessons}")
        self.stdout.write(f"  Exam marks:        {marks}")
        self.stdout.write(f"  Exam sittings:     {sittings}")
        self.stdout.write(f"  Grade bands:       {bands}")
        self.stdout.write(f"  Attendance days:   {attendance}")
        self.stdout.write(f"  E-learn attendance:{elearn_att}")
        self.stdout.write(f"  Conduct/activities:{conduct}")
        self.stdout.write(f"  Lesson plans:      {plans}")
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

    def _seed_grade_bands(self, levels):
        defaults = [
            ("A", "Exceeding expectations", "Distinction", 12, 80, 100),
            ("B", "Meeting expectations", "Credit", 9, 65, 79),
            ("C", "Approaching expectations", "Pass", 6, 50, 64),
            ("D", "Below expectations", "Weak pass", 3, 40, 49),
            ("E", "Below expectations", "Fail", 1, 0, 39),
        ]
        created = 0
        # Global default bands (academic_level NULL) — MariaDB treats NULLs as distinct.
        for code, mark_level, meaning, points, start, end in defaults:
            exists = GradeBand.objects.filter(academic_level__isnull=True, code=code).exists()
            if not exists:
                GradeBand.objects.create(
                    academic_level=None,
                    code=code,
                    mark_level=mark_level,
                    meaning=meaning,
                    points=points,
                    start_percent=start,
                    end_percent=end,
                )
                created += 1
        # Also attach to first undergraduate level for level-specific reports
        target = next((lv for lv in levels if lv.code == "Y1"), levels[0] if levels else None)
        if target:
            for code, mark_level, meaning, points, start, end in defaults:
                _, made = GradeBand.objects.get_or_create(
                    academic_level=target,
                    code=code,
                    defaults={
                        "mark_level": mark_level,
                        "meaning": meaning,
                        "points": points,
                        "start_percent": start,
                        "end_percent": end,
                    },
                )
                if made:
                    created += 1
        self.stdout.write(self.style.SUCCESS(f"Grade bands ready (+{created} new)"))
        return created

    def _seed_exam_sittings_and_supervisors(self, classes, subjects, teachers, head):
        if not classes or not subjects or not teachers:
            return 0

        profile, _ = ExamScheduleProfile.objects.get_or_create(
            name="BKC SEMESTER CAT PROFILE",
            category="UNDERGRADUATE",
            defaults={
                "first_exam_start_time": time(8, 0),
                "last_exam_end_time": time(17, 0),
                "exam_session_duration_minutes": 120,
            },
        )
        levels = [c.academic_level for c in classes[:6]]
        profile.academic_levels.set({lv.pk: lv for lv in levels}.values())
        for order, (name, start) in enumerate(
            [("Morning paper", time(8, 0)), ("Afternoon paper", time(14, 0))],
            start=1,
        ):
            ExamScheduleActivity.objects.get_or_create(
                profile=profile,
                name=name,
                defaults={"start_time": start, "duration_minutes": 120, "order": order},
            )
            ExamTimetableSession.objects.get_or_create(
                profile=profile,
                name=name,
                defaults={"start_time": start, "duration_minutes": 120, "order": order},
            )

        exam = GeneratedExamTimetable.objects.filter(name="BKC SEMESTER 1 CAT 2026").first()
        if exam is None:
            return 0

        created = 0
        for i, klass in enumerate(classes[:6]):
            area = subjects[i % len(subjects)]
            if not area.academic_levels.filter(pk=klass.academic_level_id).exists():
                area = next(
                    (
                        s
                        for s in subjects
                        if s.academic_levels.filter(pk=klass.academic_level_id).exists()
                    ),
                    subjects[0],
                )
            supervisor = teachers[i % len(teachers)]
            ExamSupervisorAllocation.objects.get_or_create(
                academic_class=klass,
                learning_area=area,
                defaults={"supervisor": supervisor},
            )
            sitting_day = date.today() - timedelta(days=(i % 5) + 1)
            _, made = GeneratedExamSitting.objects.get_or_create(
                generation=exam,
                academic_class=klass,
                learning_area=area,
                exam_date=sitting_day,
                defaults={
                    "academic_level": klass.academic_level,
                    "supervisor": supervisor,
                    "weekday": ["MON", "TUE", "WED", "THU", "FRI"][sitting_day.weekday()],
                    "period_name": "Morning paper" if i % 2 == 0 else "Afternoon paper",
                    "start_time": time(8, 0) if i % 2 == 0 else time(14, 0),
                    "end_time": time(10, 0) if i % 2 == 0 else time(16, 0),
                },
            )
            if made:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Exam sittings/supervisors: {created}"))
        return created

    def _seed_conduct_and_activities(self, levels, head):
        students = list(
            Student.objects.filter(
                assessment_number__in=[f"ASM{1001 + i}" for i in range(10)],
                is_active=True,
            )
        )
        created = 0
        samples = [
            (StudentConductRecord.BehaviourType.GOOD, "Excellent class presentation", "Certificate of recognition", 5),
            (StudentConductRecord.BehaviourType.GOOD, "Helped organize career fair", "Commendation letter", 4),
            (StudentConductRecord.BehaviourType.BAD, "Late submission of CAT without notice", "Warning and makeup session", 2),
            (StudentConductRecord.BehaviourType.BAD, "Missed industrial attachment briefing", "Mandatory catch-up briefing", 3),
            (StudentConductRecord.BehaviourType.GOOD, "Peer tutoring in accounting lab", "Merit points", 4),
            (StudentConductRecord.BehaviourType.GOOD, "Represented college at debate", "Trophy recognition", 5),
            (StudentConductRecord.BehaviourType.BAD, "Phone use during lecture", "Phone surrendered for day", 2),
            (StudentConductRecord.BehaviourType.GOOD, "Led SRC community clean-up", "Service award", 5),
            (StudentConductRecord.BehaviourType.BAD, "Noisy in library study zone", "Written apology", 1),
            (StudentConductRecord.BehaviourType.GOOD, "Volunteered at open day", "Appreciation note", 4),
        ]
        for i, student in enumerate(students):
            btype, desc, outcome, rating = samples[i % len(samples)]
            exists = StudentConductRecord.objects.filter(
                student=student, description=desc
            ).exists()
            if not exists:
                StudentConductRecord.objects.create(
                    student=student,
                    behaviour_type=btype,
                    description=desc,
                    incident_date=date.today() - timedelta(days=i + 2),
                    witness="Dean of Students",
                    consequence_or_reward=outcome,
                    rating=rating,
                    recorded_by=head,
                )
                created += 1

        activity_specs = [
            ("Career Week 2026", "Industry talks and CV clinics for all years."),
            ("Industrial Attachment Orientation", "Briefing for Diploma and Year 3/4 cohorts."),
            ("Sports Day", "Inter-programme games and wellness."),
            ("Cultural Festival", "Music, drama and cultural exhibitions."),
            ("Research Symposium", "Student project poster presentations."),
        ]
        for title, description in activity_specs:
            activity, made = SchoolActivity.objects.get_or_create(
                title=title,
                defaults={
                    "description": description,
                    "status": SchoolActivity.Status.PUBLISHED,
                    "created_by": head,
                },
            )
            if made:
                created += 1
            activity.status = SchoolActivity.Status.PUBLISHED
            activity.save(update_fields=["status"])
            activity.grades.set(levels[:6] or levels)
            for d in range(2):
                SchoolActivityDay.objects.get_or_create(
                    activity=activity,
                    activity_date=date.today() + timedelta(days=7 + d),
                    defaults={"day_description": f"Day {d + 1} — {title}"},
                )

        self.stdout.write(self.style.SUCCESS(f"Conduct + activities rows touched: {created}"))
        return created

    def _seed_lesson_plans(self, teachers):
        created = 0
        for alloc in ClassSubjectAllocation.objects.select_related("learning_area")[:15]:
            _, made = ClassSubjectLessonPlan.objects.get_or_create(
                allocation=alloc,
                defaults={
                    "strand": alloc.learning_area.name,
                    "substrand": "Unit introduction and applied practice",
                    "lesson_learning_outcomes": (
                        f"By the end of the session learners can apply core concepts in "
                        f"{alloc.learning_area.name}."
                    ),
                    "key_inquiry_questions": "How does this unit apply in the Kenyan workplace?",
                    "core_competencies": "Critical thinking; communication; digital literacy",
                    "values": "Integrity; responsibility; teamwork",
                    "learning_resources": "Lecture notes, LMS materials, case studies",
                    "introduction": "Review previous session and outline today's outcomes.",
                    "lesson_development": "Guided practice, discussion, and short formative task.",
                    "updated_by": teachers[0] if teachers else None,
                },
            )
            if made:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Lesson plans: {created}"))
        return created

    def _seed_elearning_attendance(self, teachers):
        created = 0
        students = list(
            Student.objects.filter(
                assessment_number__in=[f"ASM{1001 + i}" for i in range(10)],
                is_active=True,
            )
        )
        statuses = [
            ELearningAttendanceRecord.Status.PRESENT,
            ELearningAttendanceRecord.Status.PRESENT,
            ELearningAttendanceRecord.Status.LATE,
            ELearningAttendanceRecord.Status.ABSENT,
            ELearningAttendanceRecord.Status.EXCUSED,
        ]
        for alloc in ELearningSubjectAllocation.objects.select_related("teacher")[:8]:
            for offset in range(3):
                lesson_date = date.today() - timedelta(days=offset + 1)
                if lesson_date.weekday() >= 5:
                    continue
                session, _ = ELearningAttendanceSession.objects.get_or_create(
                    allocation=alloc,
                    lesson_date=lesson_date,
                    defaults={
                        "taken_by": alloc.teacher or (teachers[0] if teachers else None),
                        "notes": "BKC e-learning demo attendance",
                    },
                )
                for i, student in enumerate(students[:8]):
                    _, made = ELearningAttendanceRecord.objects.get_or_create(
                        session=session,
                        student=student,
                        defaults={"status": statuses[i % len(statuses)]},
                    )
                    if made:
                        created += 1
        self.stdout.write(self.style.SUCCESS(f"E-learning attendance records: {created}"))
        return created

    def _enrich_school_and_admissions(self):
        school = SchoolProfile.objects.filter(pk=1).first()
        if school:
            school.moe_code = school.moe_code or "MOE/BKC/001"
            school.nemis_number = school.nemis_number or "NEMIS-BKC-2026"
            school.knec_centre_number = school.knec_centre_number or "CDACC-BKC-01"
            school.deputy_and_admin_staff = (
                school.deputy_and_admin_staff
                or "Deputy Principal: Mrs Grace Achieng; Registrar: Mr Caleb Njoroge (pending)"
            )
            school.board_or_proprietor_info = (
                school.board_or_proprietor_info
                or "Board of Governors — Best Kenya College Trust"
            )
            school.boarding_facilities = (
                school.boarding_facilities
                or "Hostels for male and female students; mess hall; laundry"
            )
            school.transport_routes = (
                school.transport_routes
                or "Westlands shuttle; CBD evening shuttle; Thika Road pickup"
            )
            school.fee_schedule_reference = (
                school.fee_schedule_reference or "BKC/FEES/2026/SEM1"
            )
            school.social_media_links = (
                school.social_media_links
                or "Facebook: BestKenyaCollege; X: @BestKenyaCollege; Instagram: @bestkenyacollege"
            )
            school.save()

        settings = AdmissionSettings.get_solo()
        settings.admissions_enabled = True
        settings.auto_generate_admission_number = True
        settings.admission_number_prefix = "BKC/"
        settings.admission_number_pad_width = 3
        settings.admission_number_next = max(settings.admission_number_next or 1, 20)
        settings.save()
        self.stdout.write(self.style.SUCCESS("School profile + admission settings enriched"))

