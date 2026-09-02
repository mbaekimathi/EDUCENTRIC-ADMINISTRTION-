from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from apps.admissions.models import ParentGuardian, Student
from apps.curriculum.models import (
    AcademicClass,
    AcademicLevel,
    AcademicTerm,
    AcademicYear,
    ClassAttendanceRecord,
    ClassAttendanceSession,
    ExamMark,
    GeneratedExamTimetable,
    LearningArea,
)
from apps.employees.context_processors import workspace
from apps.employees.db_bulk import bulk_upsert_by_keys
from apps.employees.views import (
    _exam_record_mark_lookup,
    _exam_record_marks_lookup_multi,
    _save_exam_record_marks,
)

from .models import Employee


class StudentManagementLevelFilterTests(TestCase):
    def setUp(self):
        cache.clear()
        self.it_support = Employee.objects.create_user(
            employee_code="999001",
            password="ReliablePass456",
            title=Employee.Title.MR,
            first_name="IT",
            last_name="SUPPORT",
            email="it.support@example.com",
            phone_number="+254700000999",
            role=Employee.Role.IT_SUPPORT,
            approval_status=Employee.ApprovalStatus.APPROVED,
            is_active=True,
        )
        parent = ParentGuardian.objects.create(
            full_name="PARENT ONE",
            relationship_to_student="MOTHER",
            phone_number="+254700000001",
        )
        Student.objects.create(
            first_name="ANN",
            last_name="EAST",
            date_of_birth="2018-01-01",
            gender=Student.Gender.FEMALE,
            academic_level=Student.AcademicLevel.GRADE_1,
            admission_number="1001",
            class_group="G1E",
            assessment_number="A1001",
            sponsorship_category=Student.SponsorshipCategory.SELF,
            parent_guardian=parent,
        )
        Student.objects.create(
            first_name="BEN",
            last_name="WEST",
            date_of_birth="2018-02-02",
            gender=Student.Gender.MALE,
            academic_level=Student.AcademicLevel.GRADE_2,
            admission_number="1002",
            class_group="G2E",
            assessment_number="A1002",
            sponsorship_category=Student.SponsorshipCategory.SELF,
            parent_guardian=parent,
        )
        self.client.force_login(self.it_support)
        self.url = reverse("employees:it_support_module", kwargs={"module": "student-management"})

    def test_student_management_defaults_to_first_populated_level(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ANN EAST")
        self.assertNotContains(response, "BEN WEST")
        self.assertContains(response, "?level=GRADE_1")

    def test_student_management_level_filter_shows_selected_level_only(self):
        response = self.client.get(self.url, {"level": "GRADE_2"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "BEN WEST")
        self.assertNotContains(response, "ANN EAST")


class BulkUpsertTests(TestCase):
    def setUp(self):
        self.level = AcademicLevel.objects.create(name="Grade 1", code="G1", order=1)
        self.subject = LearningArea.objects.create(name="Math", code="MATH")
        self.subject.academic_levels.add(self.level)
        self.year = AcademicYear.objects.create(
            name="2026",
            start_date="2026-01-01",
            end_date="2026-12-31",
            is_current=True,
        )
        self.term = AcademicTerm.objects.create(
            academic_year=self.year,
            name="TERM 1",
            start_date="2026-01-01",
            end_date="2026-03-31",
            order=1,
        )
        self.generation = GeneratedExamTimetable.objects.create(
            academic_year=self.year,
            academic_term=self.term,
        )
        self.generation.academic_levels.add(self.level)
        parent = ParentGuardian.objects.create(
            full_name="PARENT ONE",
            relationship_to_student="MOTHER",
            phone_number="+254700000001",
        )
        self.student = Student.objects.create(
            first_name="ANN",
            last_name="EAST",
            date_of_birth="2018-01-01",
            gender=Student.Gender.FEMALE,
            academic_level=Student.AcademicLevel.GRADE_1,
            admission_number="1001",
            class_group="G1E",
            assessment_number="A1001",
            sponsorship_category=Student.SponsorshipCategory.SELF,
            parent_guardian=parent,
        )

    def test_bulk_upsert_creates_and_updates_exam_marks(self):
        bulk_upsert_by_keys(
            ExamMark,
            scope_filter={"generation_id": self.generation.id},
            create_defaults={"generation_id": self.generation.id},
            rows=[
                {
                    "student_id": self.student.id,
                    "learning_area_id": self.subject.id,
                    "marks": 72,
                    "out_of_marks": 100,
                }
            ],
            key_fields=("student_id", "learning_area_id"),
            update_fields=("marks", "out_of_marks"),
        )
        mark = ExamMark.objects.get(
            generation=self.generation,
            student=self.student,
            learning_area=self.subject,
        )
        self.assertEqual(mark.marks, 72)

        bulk_upsert_by_keys(
            ExamMark,
            scope_filter={"generation_id": self.generation.id},
            create_defaults={"generation_id": self.generation.id},
            rows=[
                {
                    "student_id": self.student.id,
                    "learning_area_id": self.subject.id,
                    "marks": 81,
                    "out_of_marks": 100,
                }
            ],
            key_fields=("student_id", "learning_area_id"),
            update_fields=("marks", "out_of_marks"),
        )
        mark.refresh_from_db()
        self.assertEqual(mark.marks, 81)
        self.assertEqual(ExamMark.objects.filter(generation=self.generation).count(), 1)

    def test_save_exam_record_marks_creates_and_updates(self):
        post_data = {f"mark_{self.student.id}_{self.subject.id}": "65"}
        _save_exam_record_marks(
            self.generation,
            [self.student],
            [self.subject],
            {self.subject.id: 100},
            post_data,
        )
        mark = ExamMark.objects.get(student=self.student, learning_area=self.subject)
        self.assertEqual(mark.marks, 65)

        post_data = {f"mark_{self.student.id}_{self.subject.id}": "70"}
        _save_exam_record_marks(
            self.generation,
            [self.student],
            [self.subject],
            {self.subject.id: 100},
            post_data,
        )
        mark.refresh_from_db()
        self.assertEqual(mark.marks, 70)

    def test_save_exam_record_marks_deletes_cleared_cells(self):
        ExamMark.objects.create(
            generation=self.generation,
            student=self.student,
            learning_area=self.subject,
            marks=40,
            out_of_marks=100,
        )
        _save_exam_record_marks(
            self.generation,
            [self.student],
            [self.subject],
            {self.subject.id: 100},
            {},
        )
        self.assertFalse(
            ExamMark.objects.filter(
                generation=self.generation,
                student=self.student,
                learning_area=self.subject,
            ).exists()
        )

    def test_exam_record_marks_lookup_multi_batches_generations(self):
        other_generation = GeneratedExamTimetable.objects.create(
            academic_year=self.year,
            academic_term=self.term,
        )
        other_generation.academic_levels.add(self.level)
        ExamMark.objects.create(
            generation=self.generation,
            student=self.student,
            learning_area=self.subject,
            marks=55,
            out_of_marks=100,
        )
        ExamMark.objects.create(
            generation=other_generation,
            student=self.student,
            learning_area=self.subject,
            marks=66,
            out_of_marks=100,
        )

        with self.assertNumQueries(1):
            lookups = _exam_record_marks_lookup_multi(
                [self.generation, other_generation],
                [self.student],
                [self.subject],
            )

        self.assertEqual(
            lookups[self.generation.id][(self.student.id, self.subject.id)]["marks"],
            55,
        )
        self.assertEqual(
            lookups[other_generation.id][(self.student.id, self.subject.id)]["marks"],
            66,
        )
        self.assertEqual(
            _exam_record_mark_lookup(self.generation, [self.student], [self.subject])[
                (self.student.id, self.subject.id)
            ]["marks"],
            55,
        )


class AttendanceBulkSaveTests(TestCase):
    def setUp(self):
        cache.clear()
        self.level = AcademicLevel.objects.create(name="Grade 1", code="G1", order=1)
        self.academic_class = AcademicClass.objects.create(
            academic_level=self.level,
            name="Grade 1 East",
            code="G1E",
            order=1,
        )
        self.teacher = Employee.objects.create_user(
            employee_code="123456",
            password="ReliablePass456",
            title=Employee.Title.MS,
            first_name="ALI",
            last_name="TEACHER",
            email="ali.teacher@example.com",
            phone_number="+254700000111",
            role=Employee.Role.TEACHER,
            approval_status=Employee.ApprovalStatus.APPROVED,
            is_active=True,
        )
        self.academic_class.class_teacher = self.teacher
        self.academic_class.save()
        parent = ParentGuardian.objects.create(
            full_name="PARENT ONE",
            relationship_to_student="MOTHER",
            phone_number="+254700000001",
        )
        self.student = Student.objects.create(
            first_name="ANN",
            last_name="EAST",
            date_of_birth="2018-01-01",
            gender=Student.Gender.FEMALE,
            academic_level=Student.AcademicLevel.GRADE_1,
            admission_number="1001",
            class_group="G1E",
            assessment_number="A1001",
            sponsorship_category=Student.SponsorshipCategory.SELF,
            parent_guardian=parent,
        )
        self.client.force_login(self.teacher)

    def test_class_attendance_save_uses_bulk_upsert(self):
        url = reverse(
            "employees:teacher_my_class_page",
            kwargs={"tool": "register-class-attendance"},
        )
        response = self.client.post(
            url,
            {
                "class_id": str(self.academic_class.id),
                "attendance_date": "2026-08-21",
                "attendance_notes": "Assembly day",
                f"morning_{self.student.id}": "on",
                f"afternoon_{self.student.id}": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        session = ClassAttendanceSession.objects.get(
            academic_class=self.academic_class,
            attendance_date="2026-08-21",
        )
        record = ClassAttendanceRecord.objects.get(session=session, student=self.student)
        self.assertTrue(record.morning)
        self.assertTrue(record.afternoon)
        self.assertFalse(record.evening)


class WorkspaceContextProcessorCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.teacher = Employee.objects.create_user(
            employee_code="123456",
            password="ReliablePass456",
            title=Employee.Title.MS,
            first_name="ALI",
            last_name="TEACHER",
            email="ali.teacher@example.com",
            phone_number="+254700000111",
            role=Employee.Role.TEACHER,
            approval_status=Employee.ApprovalStatus.APPROVED,
            is_active=True,
        )

    def test_teacher_nav_flags_are_cached(self):
        from django.contrib.sessions.backends.db import SessionStore
        from django.test import RequestFactory

        from apps.employees.workspace import ACTIVE_WORKSPACE_ROLE_SESSION_KEY

        request = RequestFactory().get("/")
        request.user = self.teacher
        session = SessionStore()
        session.create()
        session[ACTIVE_WORKSPACE_ROLE_SESSION_KEY] = Employee.Role.TEACHER
        session.save()
        request.session = session

        cache_key = f"teacher_nav_flags:{self.teacher.pk}"
        self.assertIsNone(cache.get(cache_key))
        workspace(request)
        self.assertIsNotNone(cache.get(cache_key))
        cached_flags = cache.get(cache_key)
        second = workspace(request)
        self.assertEqual(second["teacher_is_class_teacher"], cached_flags[0])
        self.assertEqual(second["teacher_has_elearning"], cached_flags[1])


class TeacherDashboardQueryTests(TestCase):
    def setUp(self):
        self.teacher = Employee.objects.create_user(
            employee_code="482673",
            password="ReliablePass456",
            title=Employee.Title.MR,
            first_name="ALI",
            last_name="TEACHER",
            email="ali.teacher@example.com",
            phone_number="+254700000111",
            role=Employee.Role.TEACHER,
            approval_status=Employee.ApprovalStatus.APPROVED,
            is_active=True,
        )

    def test_role_values_are_cached_on_employee_instance(self):
        with self.assertNumQueries(1):
            first = self.teacher.role_values()
            second = self.teacher.role_values()
        self.assertEqual(first, second)

    def test_teacher_dashboard_uses_bounded_queries(self):
        from django.conf import settings
        from django.db import connection, reset_queries

        settings.ALLOWED_HOSTS.append("testserver")
        client = Client()
        client.force_login(self.teacher)
        reset_queries()
        response = client.get("/workspace/teacher/")
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(connection.queries), 15)
