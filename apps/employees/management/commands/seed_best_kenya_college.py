"""
Seed demo data for Best Kenya College (idempotent).

Creates school profile, staff, curriculum skeleton, parents, and students.
Run fee seeding separately in ACCOUNTS after this command.

  python manage.py seed_best_kenya_college
  python manage.py seed_best_kenya_college --password DemoPass123!
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.admissions.models import AdmissionSettings, ParentGuardian, Student
from apps.curriculum.models import (
    AcademicClass,
    AcademicLevel,
    AcademicTerm,
    AcademicYear,
    ClassSubjectAllocation,
    ExamSubjectSetting,
    LearningArea,
)
from apps.employees.models import Employee, SchoolProfile


DEFAULT_PASSWORD = "DemoPass123!"

# 10 Kenya-style staff profiles (6-digit codes are stable for re-runs).
EMPLOYEES = [
    ("100001", "DR", "James", "Mwangi", "HEAD_OF_INSTITUTION", "james.mwangi@bestkenyacollege.ac.ke", "+254712000001"),
    ("100002", "MRS", "Grace", "Achieng", "DEPUTY_HEAD_OF_INSTITUTION", "grace.achieng@bestkenyacollege.ac.ke", "+254712000002"),
    ("100003", "TR", "Peter", "Kamau", "CURRICULUM_COORDINATOR", "peter.kamau@bestkenyacollege.ac.ke", "+254712000003"),
    ("100004", "TR", "Faith", "Wanjiru", "TEACHER", "faith.wanjiru@bestkenyacollege.ac.ke", "+254712000004"),
    ("100005", "TR", "Daniel", "Otieno", "TEACHER", "daniel.otieno@bestkenyacollege.ac.ke", "+254712000005"),
    ("100006", "TR", "Naomi", "Chebet", "TEACHER", "naomi.chebet@bestkenyacollege.ac.ke", "+254712000006"),
    ("100007", "TR", "Brian", "Kiptoo", "TEACHER", "brian.kiptoo@bestkenyacollege.ac.ke", "+254712000007"),
    ("100008", "MR", "Samuel", "Njeri", "ACCOUNTANT", "samuel.njeri@bestkenyacollege.ac.ke", "+254712000008"),
    ("100009", "MS", "Lucy", "Mutiso", "IT_SUPPORT", "lucy.mutiso@bestkenyacollege.ac.ke", "+254712000009"),
    ("100010", "MR", "Kevin", "Omondi", "STORE_MANAGER", "kevin.omondi@bestkenyacollege.ac.ke", "+254712000010"),
]

# 10 college academic levels (not primary/secondary grades).
LEVELS = [
    ("UNDERGRADUATE", "First Year", "Y1", 1),
    ("UNDERGRADUATE", "Second Year", "Y2", 2),
    ("UNDERGRADUATE", "Third Year", "Y3", 3),
    ("UNDERGRADUATE", "Fourth Year", "Y4", 4),
    ("DIPLOMA", "Diploma Year 1", "D1", 5),
    ("DIPLOMA", "Diploma Year 2", "D2", 6),
    ("CERTIFICATE", "Certificate Year 1", "C1", 7),
    ("CERTIFICATE", "Certificate Year 2", "C2", 8),
    ("FOUNDATION", "Bridging", "BR", 9),
    ("SHORT_COURSE", "Short Course", "SC", 10),
]

# Student academic_level choice aligned to LEVELS order (index).
# Labels must match AcademicLevel.name so the CLIENTS portal can resolve them.
STUDENT_LEVEL_CHOICES = [
    Student.AcademicLevel.YEAR_1,
    Student.AcademicLevel.YEAR_2,
    Student.AcademicLevel.YEAR_3,
    Student.AcademicLevel.YEAR_4,
    Student.AcademicLevel.DIPLOMA_1,
    Student.AcademicLevel.DIPLOMA_2,
    Student.AcademicLevel.CERTIFICATE_1,
    Student.AcademicLevel.CERTIFICATE_2,
    Student.AcademicLevel.BRIDGING,
    Student.AcademicLevel.SHORT_COURSE,
]

SUBJECTS = [
    ("COM", "Communication Skills", 1),
    ("ICT", "Computer Applications", 2),
    ("ACC", "Financial Accounting", 3),
    ("ENT", "Entrepreneurship", 4),
    ("MKT", "Principles of Marketing", 5),
    ("HRM", "Human Resource Management", 6),
    ("RES", "Research Methods", 7),
    ("ETH", "Professional Ethics", 8),
    ("STAT", "Business Statistics", 9),
    ("PROJ", "Capstone Project", 10),
]

# Programme / stream labels for class groups (college, not grade streams).
CLASS_STREAMS = [
    "Business",
    "ICT",
    "Education",
    "Hospitality",
    "Agriculture",
    "Health Sciences",
    "Engineering",
    "Media Studies",
    "Theology",
    "Community Development",
]

PARENTS = [
    ("Mary Wanjiku", "MOTHER", "+254722100001", "mary.wanjiku@example.com"),
    ("John Otieno", "FATHER", "+254722100002", "john.otieno@example.com"),
    ("Anne Chebet", "MOTHER", "+254722100003", "anne.chebet@example.com"),
    ("Paul Kamau", "FATHER", "+254722100004", "paul.kamau@example.com"),
    ("Esther Mutiso", "GUARDIAN", "+254722100005", "esther.mutiso@example.com"),
    ("David Kiprono", "FATHER", "+254722100006", "david.kiprono@example.com"),
    ("Joyce Achieng", "MOTHER", "+254722100007", "joyce.achieng@example.com"),
    ("Joseph Mwangi", "FATHER", "+254722100008", "joseph.mwangi@example.com"),
    ("Faith Njeri", "MOTHER", "+254722100009", "faith.njeri@example.com"),
    ("Henry Omondi", "GUARDIAN", "+254722100010", "henry.omondi@example.com"),
]

STUDENTS = [
    ("Amina", "W", "Hassan", "FEMALE", date(2005, 3, 12), "BKC/2026/001", "ASM1001", "Nairobi"),
    ("Brian", "K", "Otieno", "MALE", date(2004, 7, 4), "BKC/2026/002", "ASM1002", "Kisumu"),
    ("Cynthia", "", "Chebet", "FEMALE", date(2003, 1, 22), "BKC/2026/003", "ASM1003", "Eldoret"),
    ("David", "M", "Kamau", "MALE", date(2002, 11, 9), "BKC/2026/004", "ASM1004", "Thika"),
    ("Eva", "N", "Mutiso", "FEMALE", date(2004, 5, 18), "BKC/2026/005", "ASM1005", "Machakos"),
    ("Felix", "", "Kiprono", "MALE", date(2003, 9, 30), "BKC/2026/006", "ASM1006", "Kericho"),
    ("Grace", "A", "Achieng", "FEMALE", date(2005, 2, 14), "BKC/2026/007", "ASM1007", "Kisumu"),
    ("Hassan", "J", "Mwangi", "MALE", date(2004, 8, 21), "BKC/2026/008", "ASM1008", "Nyeri"),
    ("Irene", "", "Njeri", "FEMALE", date(2006, 12, 3), "BKC/2026/009", "ASM1009", "Nakuru"),
    ("James", "O", "Omondi", "MALE", date(2001, 6, 27), "BKC/2026/010", "ASM1010", "Mombasa"),
]


class Command(BaseCommand):
    help = (
        "Seed Best Kenya College demo data: school profile, 10 staff, "
        "10 levels/classes/subjects, 10 parents, 10 students (idempotent)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=DEFAULT_PASSWORD,
            help=f"Shared demo password for staff/parents/students (default: {DEFAULT_PASSWORD})",
        )
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Reset passwords for existing seeded portal users.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        password = options["password"]
        reset_passwords = options["reset_passwords"]
        self.stdout.write("Seeding Best Kenya College…")

        school = self._seed_school()
        employees = self._seed_employees(password, reset_passwords)
        levels, classes = self._seed_curriculum(employees)
        self._seed_year_terms()
        subjects = self._seed_subjects(levels, classes, employees)
        parents = self._seed_parents(password, reset_passwords)
        students = self._seed_students(parents, classes, password, reset_passwords)
        AdmissionSettings.get_solo()

        self.stdout.write(self.style.SUCCESS("Best Kenya College seed complete."))
        self.stdout.write(f"  School: {school.official_name}")
        self.stdout.write(f"  Employees: {len(employees)}")
        self.stdout.write(f"  Levels / classes: {len(levels)} / {len(classes)}")
        self.stdout.write(f"  Subjects: {len(subjects)}")
        self.stdout.write(f"  Parents / students: {len(parents)} / {len(students)}")
        self.stdout.write("")
        self.stdout.write("Demo logins (password for all): " + password)
        self.stdout.write("  Admin:     employee code 100001 (Head) … 100010")
        self.stdout.write("  Accounts:  100008 (Accountant), 100009 (IT), 100010 (Store)")
        self.stdout.write("  Parent:    phone +254722100001 … +254722100010")
        self.stdout.write("  Student:   assessment ASM1001 … ASM1010")
        self.stdout.write("")
        self.stdout.write(
            "Next (ACCOUNTS app): python manage.py seed_demo_fees"
        )

    def _seed_school(self):
        school, created = SchoolProfile.objects.get_or_create(
            pk=1,
            defaults={
                "official_name": "BEST KENYA COLLEGE",
                "display_name": "BEST KENYA COLLEGE",
                "school_type": SchoolProfile.SchoolType.MIXED,
                "ownership": SchoolProfile.Ownership.PRIVATE,
            },
        )
        school.official_name = "BEST KENYA COLLEGE"
        school.display_name = "BEST KENYA COLLEGE"
        school.school_type = SchoolProfile.SchoolType.MIXED
        school.ownership = SchoolProfile.Ownership.PRIVATE
        school.curricula = ["TVET", "DIPLOMA", "DEGREE"]
        school.county = "NAIROBI"
        school.sub_county = "WESTLANDS"
        school.ward = "PARKLANDS"
        school.physical_address = "PARKLANDS ROAD, NAIROBI"
        school.main_phone = "+254712345678"
        school.admissions_phone = "+254712345679"
        school.general_email = "info@bestkenyacollege.ac.ke"
        school.admissions_email = "admissions@bestkenyacollege.ac.ke"
        school.website = "https://bestkenyacollege.ac.ke"
        school.motto = "EXCELLENCE THROUGH DISCIPLINE"
        school.vision_statement = "TO BE A LEADING KENYAN COLLEGE NURTURING DISCIPLINED, COMPETENT GRADUATES."
        school.mission_statement = "TO PROVIDE QUALITY CERTIFICATE, DIPLOMA AND DEGREE PROGRAMMES IN A VALUES-DRIVEN ENVIRONMENT."
        school.primary_color = "#0B5E2B"
        school.principal_name = "DR JAMES MWANGI"
        school.term_structure = "THREE_TERM_KENYAN"
        school.academic_year_start = date(2026, 1, 5)
        school.academic_year_end = date(2026, 11, 20)
        school.enrollment_capacity = 1200
        school.boarding_status = "DAY_AND_BOARDING"
        school.mpesa_paybill = "400200"
        school.mpesa_till_number = "884455"
        school.bank_details = "EQUITY BANK — BEST KENYA COLLEGE — ACC 0123456789012"
        school.grade_levels_offered = "FIRST YEAR – FOURTH YEAR, DIPLOMA, CERTIFICATE, BRIDGING, SHORT COURSE"
        school.streams_offered = "BUSINESS, ICT, EDUCATION, HOSPITALITY, HEALTH SCIENCES"
        school.save()
        self.stdout.write(
            self.style.SUCCESS(f"{'Created' if created else 'Updated'} school profile")
        )
        return school

    def _seed_employees(self, password, reset_passwords):
        teachers = []
        created_n = 0
        for code, title, first, last, role, email, phone in EMPLOYEES:
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
                    approval_status=Employee.ApprovalStatus.APPROVED,
                )
                created_n += 1
            else:
                emp.email = email
                emp.title = title
                emp.first_name = first
                emp.last_name = last
                emp.phone_number = phone
                emp.role = role
                emp.approval_status = Employee.ApprovalStatus.APPROVED
                emp.is_suspended = False
                if reset_passwords:
                    emp.set_password(password)
                emp.save()
            emp.set_roles([role], primary=role)
            if role == Employee.Role.TEACHER:
                teachers.append(emp)
        self.stdout.write(
            self.style.SUCCESS(f"Employees ready ({created_n} new, {len(EMPLOYEES)} total)")
        )
        return list(Employee.objects.filter(employee_code__in=[e[0] for e in EMPLOYEES]))

    def _seed_curriculum(self, employees):
        teachers = [e for e in employees if e.has_role(Employee.Role.TEACHER)]
        levels = []
        classes = []
        # Hide earlier primary/secondary demo levels if this college seed re-runs.
        AcademicLevel.objects.filter(
            code__in=["PP1", "PP2", "G1", "G2", "G4", "G6", "G7", "G8", "G9", "F1"]
        ).update(status=AcademicLevel.Status.INACTIVE)
        for i, (category, name, code, order) in enumerate(LEVELS):
            level, _ = AcademicLevel.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "order": order,
                    "status": AcademicLevel.Status.ACTIVE,
                    "description": f"{name} at Best Kenya College",
                },
            )
            level.name = name
            level.category = category
            level.order = order
            level.status = AcademicLevel.Status.ACTIVE
            level.save()
            levels.append(level)

            stream = CLASS_STREAMS[i % len(CLASS_STREAMS)]
            class_code = f"{code}-{stream[:3].upper()}"
            class_name = f"{name} — {stream}"
            teacher = teachers[i % len(teachers)] if teachers else None
            klass, _ = AcademicClass.objects.get_or_create(
                academic_level=level,
                code=class_code,
                defaults={
                    "name": class_name,
                    "order": 1,
                    "status": AcademicClass.Status.ACTIVE,
                    "class_teacher": teacher,
                },
            )
            klass.name = class_name
            klass.order = 1
            klass.status = AcademicClass.Status.ACTIVE
            klass.class_teacher = teacher
            klass.save()
            classes.append(klass)

        self.stdout.write(self.style.SUCCESS(f"Levels/classes: {len(levels)}/{len(classes)}"))
        return levels, classes

    def _seed_year_terms(self):
        year, _ = AcademicYear.objects.get_or_create(
            name="2026",
            defaults={
                "start_date": date(2026, 1, 5),
                "end_date": date(2026, 11, 20),
                "is_current": True,
                "status": AcademicYear.Status.ACTIVE,
            },
        )
        year.start_date = date(2026, 1, 5)
        year.end_date = date(2026, 11, 20)
        year.is_current = True
        year.status = AcademicYear.Status.ACTIVE
        year.save()

        terms = [
            ("Term 1", date(2026, 1, 5), date(2026, 4, 3), date(2026, 1, 5), date(2026, 2, 20), date(2026, 4, 3), 1, True),
            ("Term 2", date(2026, 5, 4), date(2026, 8, 7), date(2026, 5, 4), date(2026, 6, 19), date(2026, 8, 7), 2, False),
            ("Term 3", date(2026, 8, 31), date(2026, 11, 20), date(2026, 8, 31), date(2026, 10, 9), date(2026, 11, 20), 3, False),
        ]
        for name, start, end, opening, midterm, closing, order, current in terms:
            term, _ = AcademicTerm.objects.get_or_create(
                academic_year=year,
                name=name,
                defaults={
                    "start_date": start,
                    "end_date": end,
                    "opening_date": opening,
                    "midterm_date": midterm,
                    "closing_date": closing,
                    "order": order,
                    "is_current": current,
                },
            )
            term.start_date = start
            term.end_date = end
            term.opening_date = opening
            term.midterm_date = midterm
            term.closing_date = closing
            term.order = order
            term.is_current = current
            term.save()
        self.stdout.write(self.style.SUCCESS("Academic year 2026 + 3 terms"))
        return year

    def _seed_subjects(self, levels, classes, employees):
        teachers = [e for e in employees if e.has_role(Employee.Role.TEACHER)]
        subjects = []
        for code, name, order in SUBJECTS:
            area, _ = LearningArea.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "display_order": order,
                    "total_marks": 100,
                    "status": LearningArea.Status.ACTIVE,
                    "description": f"{name} — Best Kenya College",
                },
            )
            area.name = name
            area.display_order = order
            area.status = LearningArea.Status.ACTIVE
            area.save()
            area.academic_levels.set(levels)
            subjects.append(area)

            for level in levels:
                ExamSubjectSetting.objects.get_or_create(
                    academic_level=level,
                    learning_area=area,
                    defaults={"out_of_marks": 100, "display_order": order},
                )

        for i, klass in enumerate(classes):
            for j, area in enumerate(subjects):
                teacher = teachers[(i + j) % len(teachers)] if teachers else None
                if teacher is None:
                    continue
                ClassSubjectAllocation.objects.get_or_create(
                    academic_class=klass,
                    learning_area=area,
                    defaults={"teacher": teacher},
                )

        self.stdout.write(self.style.SUCCESS(f"Subjects + allocations: {len(subjects)}"))
        return subjects

    def _seed_parents(self, password, reset_passwords):
        parents = []
        created_n = 0
        for full_name, relationship, phone, email in PARENTS:
            parent = ParentGuardian.objects.filter(phone_number=phone).first()
            if parent is None:
                parent = ParentGuardian(
                    full_name=full_name,
                    relationship_to_student=relationship,
                    phone_number=phone,
                    email=email,
                    is_active=True,
                )
                parent.set_password(password)
                parent.save()
                created_n += 1
            else:
                parent.full_name = full_name
                parent.relationship_to_student = relationship
                parent.email = email
                parent.is_active = True
                if reset_passwords:
                    parent.set_password(password)
                parent.save()
            parents.append(parent)
        self.stdout.write(
            self.style.SUCCESS(f"Parents ready ({created_n} new, {len(parents)} total)")
        )
        return parents

    def _seed_students(self, parents, classes, password, reset_passwords):
        students = []
        created_n = 0
        for i, row in enumerate(STUDENTS):
            first, middle, last, gender, dob, adm, assess, town = row
            parent = parents[i]
            klass = classes[i]
            level_choice = STUDENT_LEVEL_CHOICES[i]
            class_group = klass.display_label

            student = Student.objects.filter(assessment_number=assess).first()
            if student is None:
                student = Student(
                    first_name=first,
                    middle_name=middle,
                    last_name=last,
                    date_of_birth=dob,
                    gender=gender,
                    academic_level=level_choice,
                    admission_number=adm,
                    assessment_number=assess,
                    class_group=class_group,
                    sponsorship_category=Student.SponsorshipCategory.SELF,
                    parent_guardian=parent,
                    home_address=f"{town}, Kenya",
                    emergency_contact=f"{parent.full_name} {parent.phone_number}",
                    enrollment_status=Student.EnrollmentStatus.ACTIVE,
                    is_active=True,
                    is_suspended=False,
                    previous_school="Local Primary School",
                )
                student.set_password(password)
                student.save()
                created_n += 1
            else:
                student.first_name = first
                student.middle_name = middle
                student.last_name = last
                student.date_of_birth = dob
                student.gender = gender
                student.academic_level = level_choice
                student.admission_number = adm
                student.class_group = class_group
                student.parent_guardian = parent
                student.enrollment_status = Student.EnrollmentStatus.ACTIVE
                student.is_active = True
                student.is_suspended = False
                if reset_passwords:
                    student.set_password(password)
                student.save()
            students.append(student)
        self.stdout.write(
            self.style.SUCCESS(f"Students ready ({created_n} new, {len(students)} total)")
        )
        return students
