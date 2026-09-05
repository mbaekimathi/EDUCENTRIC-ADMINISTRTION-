from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import IntegrityError, models, transaction


def next_employment_number():
    issued_max = IssuedEmploymentNumber.objects.aggregate(models.Max("number"))["number__max"] or 0
    employee_max = Employee.objects.aggregate(models.Max("employment_number"))[
        "employment_number__max"
    ] or 0
    return max(issued_max, employee_max) + 1


class EmployeeManager(BaseUserManager):
    """Creates users whose six-digit employee code is their identifier."""

    def create_user(self, employee_code, password=None, **extra_fields):
        if not employee_code:
            raise ValueError("An employee code is required.")
        if not extra_fields.get("email"):
            raise ValueError("An email address is required.")
        employee = self.model(employee_code=employee_code, **extra_fields)
        employee.set_password(password)
        employee.save(using=self._db)
        return employee

    def create_superuser(self, employee_code, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("approval_status", Employee.ApprovalStatus.APPROVED)
        extra_fields.setdefault("role", Employee.Role.HEAD_OF_INSTITUTION)
        return self.create_user(employee_code, password, **extra_fields)


class IssuedEmploymentNumber(models.Model):
    """Keeps every employment number that has ever been issued so it cannot be reused."""

    number = models.PositiveIntegerField(unique=True)

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return str(self.number)


class SchoolProfile(models.Model):
    class SchoolType(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary school"
        SECONDARY = "SECONDARY", "Secondary school"
        MIXED = "MIXED", "Mixed primary and secondary"
        INTERNATIONAL = "INTERNATIONAL", "International school"
        SPECIAL_NEEDS = "SPECIAL_NEEDS", "Special needs school"

    class Ownership(models.TextChoices):
        PUBLIC = "PUBLIC", "Public / government"
        PRIVATE = "PRIVATE", "Private"
        FAITH_BASED = "FAITH_BASED", "Faith-based"
        COMMUNITY = "COMMUNITY", "Community"

    official_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=120)
    school_type = models.CharField(max_length=20, choices=SchoolType.choices)
    ownership = models.CharField(max_length=20, choices=Ownership.choices)
    moe_code = models.CharField("Ministry of Education code", max_length=80, blank=True)
    nemis_number = models.CharField(max_length=80, blank=True)
    knec_centre_number = models.CharField(max_length=80, blank=True)
    curricula = models.JSONField(default=list)
    physical_address = models.TextField(blank=True)
    county = models.CharField(max_length=100, blank=True)
    sub_county = models.CharField(max_length=100, blank=True)
    ward = models.CharField(max_length=100, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    main_phone = models.CharField(max_length=24, blank=True)
    admissions_phone = models.CharField(max_length=24, blank=True)
    general_email = models.EmailField(blank=True)
    admissions_email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    social_media_links = models.TextField(blank=True)
    school_logo = models.ImageField(upload_to="school/branding/", blank=True)
    motto = models.CharField(max_length=255, blank=True)
    vision_statement = models.TextField(blank=True)
    mission_statement = models.TextField(blank=True)
    primary_color = models.CharField(max_length=7, blank=True)
    principal_name = models.CharField(max_length=255, blank=True)
    deputy_and_admin_staff = models.TextField(blank=True)
    board_or_proprietor_info = models.TextField(blank=True)
    departments = models.TextField(blank=True)
    grade_levels_offered = models.TextField(blank=True)
    streams_offered = models.TextField(blank=True)
    term_structure = models.CharField(
        max_length=100, blank=True, default="THREE_TERM_KENYAN"
    )
    academic_year_start = models.DateField(null=True, blank=True)
    academic_year_end = models.DateField(null=True, blank=True)
    enrollment_capacity = models.PositiveIntegerField(null=True, blank=True)
    boarding_status = models.CharField(max_length=30, blank=True)
    boarding_facilities = models.TextField(blank=True)
    transport_routes = models.TextField(blank=True)
    bank_details = models.TextField(blank=True)
    mpesa_paybill = models.CharField(max_length=30, blank=True)
    mpesa_till_number = models.CharField(max_length=30, blank=True)
    fee_schedule_reference = models.CharField(max_length=255, blank=True)
    registration_certificate = models.FileField(
        upload_to="school/compliance/", blank=True
    )
    inspection_report = models.FileField(upload_to="school/compliance/", blank=True)

    class Meta:
        verbose_name = "school profile"
        verbose_name_plural = "school profile"

    def __str__(self):
        return self.official_name

    @property
    def brand_name(self):
        return (self.display_name or self.official_name or "School").strip()

    @property
    def brand_official_name(self):
        return (self.official_name or self.display_name or "School").strip()

    @property
    def brand_initials(self):
        source = self.brand_name
        parts = [part for part in source.replace("-", " ").split() if part]
        if len(parts) >= 2:
            return "".join(part[0] for part in parts[:2]).upper()
        return source[:2].upper() if source else "EC"

    @property
    def brand_accent(self):
        color = (self.primary_color or "").strip()
        if len(color) == 7 and color.startswith("#"):
            return color
        if len(color) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in color):
            return f"#{color}"
        return "#1f5cf0"

    @property
    def has_logo_file(self):
        name = getattr(self.school_logo, "name", "") or ""
        if not name:
            return False
        try:
            return self.school_logo.storage.exists(name)
        except Exception:
            return False

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            from django.core.cache import cache

            cache.delete("school_profile_branding_v1")
        except Exception:
            pass


class Employee(AbstractUser):
    class Title(models.TextChoices):
        MR = "MR", "Mr."
        MRS = "MRS", "Mrs."
        MISS = "MISS", "Miss"
        MS = "MS", "Ms."
        TR = "TR", "Tr."
        DR = "DR", "Dr."
        PROF = "PROF", "Prof."

    class Role(models.TextChoices):
        EMPLOYEE = "EMPLOYEE", "Employee"
        HEAD_OF_INSTITUTION = "HEAD_OF_INSTITUTION", "Head of Institution"
        DEPUTY_HEAD_OF_INSTITUTION = "DEPUTY_HEAD_OF_INSTITUTION", "Deputy Head of Institution"
        CURRICULUM_COORDINATOR = "CURRICULUM_COORDINATOR", "Curriculum Coordinator"
        TEACHER = "TEACHER", "Teacher"
        ACCOUNTANT = "ACCOUNTANT", "Accountant"
        LIBRARIAN = "LIBRARIAN", "Librarian"
        STORE_MANAGER = "STORE_MANAGER", "Store Manager"
        WARDEN = "WARDEN", "Warden"
        SECRETARY = "SECRETARY", "Secretary"
        IT_SUPPORT = "IT_SUPPORT", "IT Support"

    class ApprovalStatus(models.TextChoices):
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    username = None
    employee_code = models.CharField(
        max_length=6,
        unique=True,
        validators=[RegexValidator(r"^\d{6}$", "Enter exactly six digits.")],
        help_text="Six-digit employee identification code.",
    )
    employment_number = models.PositiveIntegerField(
        unique=True,
        null=True,
        blank=True,
        help_text="Whole number starting from 1. Assigned automatically on registration and can be edited, but never reused.",
    )
    title = models.CharField(max_length=4, choices=Title.choices)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=24)
    profile_image = models.ImageField(upload_to="employees/profiles/", blank=True)
    role = models.CharField(
        max_length=32,
        choices=Role.choices,
        default=Role.EMPLOYEE,
    )
    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING_APPROVAL,
    )
    is_suspended = models.BooleanField(
        default=False,
        help_text="Suspended employees cannot log in, even if they are approved.",
    )
    is_active = models.BooleanField(
        default=False,
        help_text="Designates whether this user can log in.",
    )

    USERNAME_FIELD = "employee_code"
    REQUIRED_FIELDS = ["email", "first_name", "last_name", "title"]

    objects = EmployeeManager()

    class Meta:
        ordering = ["last_name", "first_name"]

    @property
    def display_name(self):
        title = self.get_title_display() if self.title else ""
        return f"{title} {self.first_name} {self.last_name}".strip()

    @property
    def is_approved(self):
        return self.approval_status == self.ApprovalStatus.APPROVED

    def role_values(self):
        """Return all assigned role codes; fall back to primary role if none assigned yet."""
        cached = getattr(self, "_cached_role_values", None)
        if cached is not None:
            return cached
        if self.pk:
            values = list(
                self.assigned_roles.order_by("role").values_list("role", flat=True)
            )
            if values:
                self._cached_role_values = values
                return values
        values = [self.role] if self.role else []
        self._cached_role_values = values
        return values

    def role_labels(self):
        labels = dict(self.Role.choices)
        return [labels.get(role, role) for role in self.role_values()]

    def has_role(self, role):
        return role in self.role_values()

    def set_roles(self, roles, primary=None):
        """Replace assigned roles and keep Employee.role as the primary/default."""
        valid = {value for value, _label in self.Role.choices}
        cleaned = []
        for role in roles or []:
            role = (role or "").strip().upper()
            if role in valid and role not in cleaned:
                cleaned.append(role)
        if not cleaned:
            raise ValidationError({"roles": "Select at least one role."})
        if primary:
            primary = primary.strip().upper()
        if primary not in cleaned:
            primary = self.role if self.role in cleaned else cleaned[0]

        if not self.pk:
            self.role = primary
            self.save()

        existing = set(self.assigned_roles.values_list("role", flat=True))
        desired = set(cleaned)
        self.assigned_roles.filter(role__in=existing - desired).delete()
        EmployeeRole.objects.bulk_create(
            [
                EmployeeRole(employee=self, role=role)
                for role in desired - existing
            ],
            ignore_conflicts=True,
        )
        if self.role != primary:
            type(self).objects.filter(pk=self.pk).update(role=primary)
            self.role = primary
        self._cached_role_values = cleaned

    def _ensure_primary_role_assignment(self):
        if not self.pk or not self.role:
            return
        if not self.assigned_roles.filter(role=self.role).exists():
            EmployeeRole.objects.get_or_create(employee=self, role=self.role)

    def _previous_employment_number(self):
        if not self.pk:
            return None
        return (
            type(self)
            .objects.filter(pk=self.pk)
            .values_list("employment_number", flat=True)
            .first()
        )

    def _claim_employment_number(self):
        number = self.employment_number
        previous = self._previous_employment_number()
        if previous == number:
            IssuedEmploymentNumber.objects.get_or_create(number=number)
            return
        if IssuedEmploymentNumber.objects.filter(number=number).exists():
            if getattr(self, "_allow_reassigned_employment_number", False):
                return
            raise ValidationError(
                {
                    "employment_number": "This employment number has already been used and cannot be reused."
                }
            )
        IssuedEmploymentNumber.objects.create(number=number)

    def save(self, *args, **kwargs):
        assigned_number = self.employment_number in (None, "")
        # Keep login access in sync with approval and suspension.
        if self.approval_status == self.ApprovalStatus.APPROVED and not self.is_suspended:
            self.is_active = True
        else:
            self.is_active = False
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            extras = {"is_active"}
            if assigned_number:
                extras.add("employment_number")
            kwargs["update_fields"] = list(set(update_fields) | extras)

        for _ in range(8):
            try:
                with transaction.atomic():
                    if self.employment_number in (None, ""):
                        self.employment_number = next_employment_number()
                        assigned_number = True
                        if update_fields is not None:
                            kwargs["update_fields"] = list(
                                set(kwargs["update_fields"]) | {"employment_number"}
                            )
                    self._claim_employment_number()
                    super().save(*args, **kwargs)
                    self._ensure_primary_role_assignment()
                return
            except IntegrityError:
                if not assigned_number:
                    raise
                self.employment_number = None
        raise IntegrityError("Could not assign a unique employment number.")

    def __str__(self):
        return f"{self.employee_code} — {self.display_name}"


class EmployeeRole(models.Model):
    """Extra workspace roles an employee may hold in addition to their primary role."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="assigned_roles",
    )
    role = models.CharField(max_length=32, choices=Employee.Role.choices)

    class Meta:
        ordering = ["role"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "role"],
                name="unique_employee_role_assignment",
            ),
        ]
        verbose_name = "employee role"
        verbose_name_plural = "employee roles"

    def __str__(self):
        return f"{self.employee.employee_code}: {self.get_role_display()}"

