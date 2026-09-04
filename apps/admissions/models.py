from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import RegexValidator
from django.db import models, transaction


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

    class EnrollmentStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        TRANSFER = "TRANSFER", "Transfer"
        ALUMNAE = "ALUMNAE", "Alumnae"

    class ClearanceReason(models.TextChoices):
        TRANSFER = "TRANSFER", "Transfer to another school"
        COMPLETED_SCHOOL = "COMPLETED_SCHOOL", "Completed school"

    first_name = models.CharField(max_length=150)
    middle_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=10, choices=Gender.choices)
    academic_level = models.CharField(max_length=20, choices=AcademicLevel.choices)
    admission_number = models.CharField(max_length=40, unique=True, null=True, blank=True)
    class_group = models.CharField(max_length=50, blank=True)
    assessment_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
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
    enrollment_status = models.CharField(
        max_length=20,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.ACTIVE,
        help_text="School enrollment status: active, transfer, or alumnae.",
    )
    clearance_reason = models.CharField(
        max_length=30,
        choices=ClearanceReason.choices,
        blank=True,
        help_text="Reason recorded when the student was cleared.",
    )
    cleared_at = models.DateTimeField(null=True, blank=True)
    admitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["last_name", "first_name", "middle_name"]
        indexes = [
            models.Index(fields=["academic_level"], name="student_academic_level_idx"),
            models.Index(fields=["class_group"], name="student_class_group_idx"),
            models.Index(
                fields=["academic_level", "class_group"],
                name="student_level_class_idx",
            ),
            models.Index(fields=["enrollment_status"], name="student_enrollment_status_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.is_suspended:
            self.is_active = False
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = list(set(update_fields) | {"is_active"})
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(part for part in parts if part).strip()

    def __str__(self):
        label = self.assessment_number or self.admission_number or "NO ID"
        return f"{label} — {self.display_name}"


class AdmissionSettings(models.Model):
    """Singleton configuration for the admissions module."""

    admissions_enabled = models.BooleanField(
        default=True,
        help_text="When off, new student admissions are blocked.",
    )
    auto_generate_admission_number = models.BooleanField(
        default=True,
        help_text=(
            "When on, the admit form suggests the next admission number. "
            "Staff can edit the suggested value before saving."
        ),
    )
    admission_number_prefix = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Optional text placed before the number, e.g. ADM or 2026/.",
    )
    admission_number_next = models.PositiveIntegerField(
        default=1,
        help_text="Numeric part of the next admission number suggested on the admit form.",
    )
    admission_number_pad_width = models.PositiveSmallIntegerField(
        default=0,
        help_text="Minimum digits for the numeric part. Use 0 for no padding (e.g. 4 → 0001).",
    )

    class Meta:
        verbose_name = "admission settings"
        verbose_name_plural = "admission settings"

    def __str__(self):
        return "Admission settings"

    def format_admission_number(self, number):
        numeric = max(1, int(number or 1))
        width = max(0, int(self.admission_number_pad_width or 0))
        if width:
            numeric_text = f"{numeric:0{width}d}"
        else:
            numeric_text = str(numeric)
        prefix = (self.admission_number_prefix or "").strip().upper()
        return f"{prefix}{numeric_text}"

    def preview_next_admission_number(self):
        number = max(1, self.admission_number_next or 1)
        while Student.objects.filter(
            admission_number=self.format_admission_number(number)
        ).exists():
            number += 1
        return self.format_admission_number(number)

    @classmethod
    def suggested_next_number(cls):
        """Highest purely numeric trailing sequence currently in use, plus one."""
        numbers = (
            Student.objects.exclude(admission_number__isnull=True)
            .exclude(admission_number="")
            .values_list("admission_number", flat=True)
        )
        highest = 0
        for value in numbers:
            text = str(value).strip()
            digits = ""
            for char in reversed(text):
                if char.isdigit():
                    digits = char + digits
                elif digits:
                    break
            if digits:
                highest = max(highest, int(digits))
            elif text.isdigit():
                highest = max(highest, int(text))
        return highest + 1 if highest else 1

    @classmethod
    def get_solo(cls):
        obj, created = cls.objects.get_or_create(
            pk=1,
            defaults={"admission_number_next": cls.suggested_next_number()},
        )
        return obj

    @classmethod
    def peek_next_admission_number(cls):
        """Return the next suggested admission number without reserving it."""
        return cls.get_solo().preview_next_admission_number()

    @classmethod
    def allocate_next_admission_number(cls):
        """Reserve and return the next admission number as a string."""
        with transaction.atomic():
            settings = cls.objects.select_for_update().filter(pk=1).first()
            if settings is None:
                settings = cls.objects.create(
                    pk=1,
                    admission_number_next=cls.suggested_next_number(),
                )
                settings = cls.objects.select_for_update().get(pk=1)

            number = max(1, settings.admission_number_next or 1)
            while True:
                candidate = settings.format_admission_number(number)
                if not Student.objects.filter(admission_number=candidate).exists():
                    break
                number += 1
            settings.admission_number_next = number + 1
            settings.save(update_fields=["admission_number_next"])
            return candidate

    @classmethod
    def advance_past_admission_number(cls, used_number):
        """Bump the next-number counter past a used admission number when possible."""
        text = str(used_number or "").strip().upper()
        if not text:
            return
        with transaction.atomic():
            settings = cls.objects.select_for_update().filter(pk=1).first()
            if settings is None:
                settings = cls.objects.create(
                    pk=1,
                    admission_number_next=cls.suggested_next_number(),
                )
                settings = cls.objects.select_for_update().get(pk=1)

            prefix = (settings.admission_number_prefix or "").strip().upper()
            numeric_part = text
            if prefix and text.startswith(prefix):
                numeric_part = text[len(prefix) :]
            if not numeric_part.isdigit():
                digits = ""
                for char in reversed(text):
                    if char.isdigit():
                        digits = char + digits
                    elif digits:
                        break
                if not digits:
                    return
                used = int(digits)
            else:
                used = int(numeric_part)

            next_number = max(settings.admission_number_next or 1, used + 1)
            while Student.objects.filter(
                admission_number=settings.format_admission_number(next_number)
            ).exists():
                next_number += 1
            if next_number != settings.admission_number_next:
                settings.admission_number_next = next_number
                settings.save(update_fields=["admission_number_next"])
