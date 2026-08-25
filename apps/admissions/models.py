from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import RegexValidator
from django.db import models


class PortalAccount(models.Model):
    """Shared secure password and activation fields for non-employee portals."""

    password = models.CharField(max_length=128, blank=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        abstract = True

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return bool(self.password) and check_password(raw_password, self.password)


class ParentGuardian(PortalAccount):
    full_name = models.CharField(max_length=200)
    relationship_to_student = models.CharField(max_length=80)
    phone_number = models.CharField(
        max_length=24,
        unique=True,
        validators=[RegexValidator(r"^\+?[0-9\s-]{7,24}$", "Enter a valid phone number.")],
    )
    email = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.phone_number})"


class Student(PortalAccount):
    class Gender(models.TextChoices):
        FEMALE = "FEMALE", "Female"
        MALE = "MALE", "Male"
        OTHER = "OTHER", "Other"

    class AcademicLevel(models.TextChoices):
        PRE_PRIMARY_1 = "PRE_PRIMARY_1", "Pre-Primary 1"
        PRE_PRIMARY_2 = "PRE_PRIMARY_2", "Pre-Primary 2"
        GRADE_1 = "GRADE_1", "Grade 1"
        GRADE_2 = "GRADE_2", "Grade 2"
        GRADE_3 = "GRADE_3", "Grade 3"
        GRADE_4 = "GRADE_4", "Grade 4"
        GRADE_5 = "GRADE_5", "Grade 5"
        GRADE_6 = "GRADE_6", "Grade 6"
        GRADE_7 = "GRADE_7", "Grade 7"
        GRADE_8 = "GRADE_8", "Grade 8"
        GRADE_9 = "GRADE_9", "Grade 9"
        FORM_1 = "FORM_1", "Form 1"
        FORM_2 = "FORM_2", "Form 2"
        FORM_3 = "FORM_3", "Form 3"
        FORM_4 = "FORM_4", "Form 4"
        OTHER = "OTHER", "Other"

    class SponsorshipCategory(models.TextChoices):
        GOVERNMENT = "GOVERNMENT", "Government sponsored"
        SELF = "SELF", "Self sponsored"
        BOTH = "BOTH", "Government and self sponsored"

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=10, choices=Gender.choices)
    academic_level = models.CharField(max_length=20, choices=AcademicLevel.choices)
    admission_number = models.CharField(max_length=40, unique=True, null=True, blank=True)
    class_group = models.CharField(max_length=50, blank=True)
    assessment_number = models.CharField(max_length=50, unique=True)
    previous_school = models.CharField(max_length=200, blank=True)
    profile_image = models.ImageField(upload_to="students/profiles/", blank=True)
    sponsorship_category = models.CharField(
        max_length=20,
        choices=SponsorshipCategory.choices,
    )
    sponsor_details = models.TextField(blank=True)
    parent_guardian = models.ForeignKey(
        ParentGuardian,
        on_delete=models.PROTECT,
        related_name="students",
    )
    home_address = models.TextField(blank=True)
    medical_notes = models.TextField(blank=True)
    special_needs = models.TextField(blank=True)
    emergency_contact = models.CharField(max_length=200, blank=True)
    is_suspended = models.BooleanField(
        default=False,
        help_text="Suspended students cannot use the student portal.",
    )
    admitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def save(self, *args, **kwargs):
        if self.is_suspended:
            self.is_active = False
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = list(set(update_fields) | {"is_active"})
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return f"{self.assessment_number} — {self.display_name}"

# Create your models here.
