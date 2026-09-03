from django.test import TestCase
from django.urls import reverse

from apps.employees.models import Employee

from .models import ParentGuardian, Student


class AdmissionsTests(TestCase):
    def setUp(self):
        self.employee = Employee.objects.create_user(
            employee_code="123456",
            password="EMPLOYEE-PASSWORD-456",
            title=Employee.Title.MR,
            first_name="ADMIN",
            last_name="USER",
            email="admin@example.com",
            phone_number="+254700000001",
            approval_status=Employee.ApprovalStatus.APPROVED,
            is_active=True,
        )
        self.parent = ParentGuardian.objects.create(
            full_name="JANE DOE",
            relationship_to_student="MOTHER",
            phone_number="+254700000002",
            email="jane@example.com",
            is_active=True,
        )
        self.parent.set_password("ParentPass456")
        self.parent.save()
        self.student = Student.objects.create(
            first_name="JOHN",
            last_name="DOE",
            date_of_birth="2015-01-01",
            gender=Student.Gender.MALE,
            academic_level=Student.AcademicLevel.GRADE_4,
            assessment_number="ASSESS-001",
            sponsorship_category=Student.SponsorshipCategory.SELF,
            parent_guardian=self.parent,
            is_active=True,
        )
        self.student.set_password("StudentPass456")
        self.student.save()

    def test_employee_can_admit_student(self):
        self.client.force_login(self.employee)
        response = self.client.post(
            reverse("admissions:admit_student"),
            {
                "first_name": "Grace",
                "last_name": "Wanjiku",
                "date_of_birth": "2016-04-15",
                "gender": "FEMALE",
                "academic_level": "GRADE_3",
                "assessment_number": "ASSESS-002",
                "previous_school": "Bright School",
                "sponsorship_category": "GOVERNMENT",
                "sponsor_details": "County bursary",
                "parent_guardian_name": "Mary Wanjiku",
                "relationship_to_student": "Mother",
                "parent_phone": "+254700000003",
                "parent_email": "mary@example.com",
                "home_address": "Nairobi",
            },
        )
        self.assertRedirects(response, reverse("admissions:admit_student"))
        admitted = Student.objects.get(assessment_number="ASSESS-002")
        self.assertFalse(admitted.is_active)
        self.assertFalse(admitted.parent_guardian.is_active)
        self.assertEqual(admitted.emergency_contact, "+254700000003")

    def test_employee_can_admit_student_without_assessment_number(self):
        self.client.force_login(self.employee)
        response = self.client.post(
            reverse("admissions:admit_student"),
            {
                "first_name": "Amina",
                "last_name": "Hassan",
                "date_of_birth": "2017-08-20",
                "gender": "FEMALE",
                "academic_level": "GRADE_2",
                "assessment_number": "",
                "previous_school": "",
                "sponsorship_category": "SELF",
                "sponsor_details": "",
                "parent_guardian_name": "Hassan Ali",
                "relationship_to_student": "Father",
                "parent_phone": "+254700000004",
                "parent_email": "",
                "home_address": "",
            },
        )
        self.assertRedirects(response, reverse("admissions:admit_student"))
        admitted = Student.objects.get(first_name="AMINA", last_name="HASSAN")
        self.assertIsNone(admitted.assessment_number)

    def test_student_can_access_student_portal(self):
        response = self.client.post(
            reverse("admissions:portal_login"),
            {
                "portal_type": "student",
                "student-assessment_number": "ASSESS-001",
                "student-password": "StudentPass456",
            },
        )
        self.assertRedirects(response, reverse("admissions:student_portal"))

    def test_parent_can_access_parent_portal(self):
        response = self.client.post(
            reverse("admissions:portal_login"),
            {
                "portal_type": "parent",
                "parent-phone_number": "+254700000002",
                "parent-password": "ParentPass456",
            },
        )
        self.assertRedirects(response, reverse("admissions:parent_portal"))

# Create your tests here.
