from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Employee, IssuedEmploymentNumber, SchoolProfile
from .phone_countries import PHONE_COUNTRIES, country_by_iso, normalize_phone, parse_stored_phone


def uppercase_value(value):
    if isinstance(value, str):
        return value.strip().upper()
    return value


class UppercaseFieldsMixin:
    """Force selected text fields to uppercase in the UI and on save."""

    uppercase_fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.uppercase_fields:
            field = self.fields.get(name)
            if not field:
                continue
            classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{classes} uppercase-input".strip()
            field.widget.attrs.setdefault("autocapitalize", "characters")

    def clean(self):
        cleaned_data = super().clean()
        for name in self.uppercase_fields:
            value = cleaned_data.get(name)
            if isinstance(value, str):
                cleaned_data[name] = uppercase_value(value)
        return cleaned_data


class EmployeeLoginForm(forms.Form):
    employee_code = forms.CharField(
        label="Employment number",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "username",
                "inputmode": "numeric",
                "placeholder": "E.G. 123456",
                "class": "uppercase-input",
            }
        ),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "placeholder": "Enter your password",
            }
        )
    )

    def clean_employee_code(self):
        return uppercase_value(self.cleaned_data["employee_code"])

    def clean(self):
        cleaned_data = super().clean()
        employee_code = cleaned_data.get("employee_code")
        password = cleaned_data.get("password")
        if employee_code and password:
            self.user = authenticate(employee_code=employee_code, password=password)
            if self.user is None:
                employee = Employee.objects.filter(employee_code=employee_code).first()
                if employee and employee.check_password(password):
                    if employee.approval_status == Employee.ApprovalStatus.PENDING_APPROVAL:
                        raise forms.ValidationError(
                            "Your account is pending administrator approval."
                        )
                    if employee.approval_status == Employee.ApprovalStatus.REJECTED:
                        raise forms.ValidationError(
                            "Your registration was not approved. Contact your administrator."
                        )
                    if employee.is_suspended:
                        raise forms.ValidationError(
                            "Your account is suspended. Contact your administrator."
                        )
                    if (
                        employee.approval_status == Employee.ApprovalStatus.APPROVED
                        and not employee.is_active
                    ):
                        raise forms.ValidationError(
                            "Your account is approved but not activated yet. Ask an administrator to activate it."
                        )
                raise forms.ValidationError("Your employment number or password is incorrect.")
        return cleaned_data

    def get_user(self):
        return getattr(self, "user", None)


class SchoolProfileForm(UppercaseFieldsMixin, forms.ModelForm):
    CURRICULUM_CHOICES = (
        ("CBC", "CBC"),
        ("8-4-4", "8-4-4 (legacy)"),
        ("IGCSE", "IGCSE"),
        ("IB", "International Baccalaureate (IB)"),
        ("OTHER", "Other"),
    )

    curricula = forms.MultipleChoiceField(
        choices=CURRICULUM_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        label="Curriculum offered",
        help_text="Select every curriculum offered by the school.",
    )
    uppercase_fields = (
        "official_name",
        "display_name",
        "moe_code",
        "nemis_number",
        "knec_centre_number",
    )

    class Meta:
        model = SchoolProfile
        fields = (
            "official_name",
            "display_name",
            "school_logo",
            "school_type",
            "ownership",
            "moe_code",
            "nemis_number",
            "knec_centre_number",
            "curricula",
        )
        labels = {
            "official_name": "Official school name",
            "display_name": "Short / display name",
            "school_logo": "School logo",
            "school_type": "School type",
            "ownership": "Ownership",
            "moe_code": "MOE / Ministry of Education code",
            "nemis_number": "NEMIS number",
            "knec_centre_number": "KNEC centre number",
        }
        help_texts = {
            "school_logo": "Shown on the sign-in page, assessment reports, and mark sheets.",
        }
        widgets = {
            "official_name": forms.TextInput(
                attrs={"placeholder": "E.G. EDU-CENTRIC ACADEMY"}
            ),
            "display_name": forms.TextInput(
                attrs={"placeholder": "E.G. EDU-CENTRIC"}
            ),
            "school_logo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "school_type": forms.Select(attrs={"class": "uppercase-input"}),
            "ownership": forms.Select(attrs={"class": "uppercase-input"}),
            "moe_code": forms.TextInput(attrs={"placeholder": "OPTIONAL"}),
            "nemis_number": forms.TextInput(attrs={"placeholder": "OPTIONAL"}),
            "knec_centre_number": forms.TextInput(attrs={"placeholder": "OPTIONAL"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.curricula:
            self.fields["curricula"].initial = self.instance.curricula
        self.fields["school_logo"].required = False


class SchoolProfileContactLocationForm(UppercaseFieldsMixin, forms.ModelForm):
    uppercase_fields = (
        "physical_address",
        "county",
        "sub_county",
        "ward",
        "main_phone",
        "admissions_phone",
    )

    class Meta:
        model = SchoolProfile
        fields = (
            "physical_address", "county", "sub_county", "ward", "latitude",
            "longitude", "main_phone", "admissions_phone", "general_email",
            "admissions_email", "website", "social_media_links",
        )
        widgets = {
            "physical_address": forms.Textarea(attrs={"rows": 3}),
            "latitude": forms.NumberInput(attrs={"step": "0.000001"}),
            "longitude": forms.NumberInput(attrs={"step": "0.000001"}),
            "social_media_links": forms.Textarea(
                attrs={"rows": 3, "placeholder": "One URL per line"}
            ),
        }
        labels = {
            "general_email": "General email",
            "admissions_email": "Admissions email",
            "main_phone": "Main phone line",
            "admissions_phone": "Admissions phone line",
            "social_media_links": "Social media links",
        }


class SchoolProfileBrandingForm(UppercaseFieldsMixin, forms.ModelForm):
    uppercase_fields = ("motto", "vision_statement", "mission_statement")

    class Meta:
        model = SchoolProfile
        fields = ("school_logo", "motto", "vision_statement", "mission_statement", "primary_color")
        labels = {
            "school_logo": "School logo",
            "primary_color": "Primary colour",
        }
        help_texts = {
            "school_logo": "Appears on the sign-in page, assessment reports, and mark sheets.",
            "primary_color": "Used as the accent colour on the public sign-in experience.",
        }
        widgets = {
            "school_logo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "vision_statement": forms.Textarea(attrs={"rows": 4}),
            "mission_statement": forms.Textarea(attrs={"rows": 4}),
            "primary_color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["school_logo"].required = False
        if self.instance and self.instance.pk and self.instance.primary_color:
            self.fields["primary_color"].initial = self.instance.primary_color
        else:
            self.fields["primary_color"].initial = "#1f5cf0"

    def clean_primary_color(self):
        color = (self.cleaned_data.get("primary_color") or "").strip()
        if not color:
            return "#1f5cf0"
        if len(color) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in color):
            color = f"#{color}"
        if not (len(color) == 7 and color.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in color[1:])):
            raise forms.ValidationError("Choose a valid colour.")
        return color.lower()


class SchoolProfileLeadershipForm(UppercaseFieldsMixin, forms.ModelForm):
    uppercase_fields = (
        "principal_name",
        "deputy_and_admin_staff",
        "board_or_proprietor_info",
        "departments",
    )

    class Meta:
        model = SchoolProfile
        fields = (
            "principal_name", "deputy_and_admin_staff",
            "board_or_proprietor_info", "departments",
        )
        widgets = {
            "deputy_and_admin_staff": forms.Textarea(
                attrs={"rows": 4, "placeholder": "ONE PERSON AND ROLE PER LINE"}
            ),
            "board_or_proprietor_info": forms.Textarea(attrs={"rows": 4}),
            "departments": forms.Textarea(
                attrs={"rows": 4, "placeholder": "ONE DEPARTMENT PER LINE"}
            ),
        }
        labels = {
            "principal_name": "Principal / head teacher",
            "deputy_and_admin_staff": "Deputy and administrative staff",
            "board_or_proprietor_info": "Board of management / proprietor information",
        }


class SchoolProfileAcademicSetupForm(UppercaseFieldsMixin, forms.ModelForm):
    TERM_CHOICES = (
        ("THREE_TERM_KENYAN", "Three-term Kenyan calendar"),
        ("TWO_TERM", "Two-term calendar"),
        ("OTHER", "Other"),
    )
    term_structure = forms.ChoiceField(
        choices=TERM_CHOICES,
        widget=forms.Select(attrs={"class": "uppercase-input"}),
    )
    uppercase_fields = ("grade_levels_offered", "streams_offered")

    class Meta:
        model = SchoolProfile
        fields = (
            "grade_levels_offered", "streams_offered", "term_structure",
            "academic_year_start", "academic_year_end",
        )
        widgets = {
            "grade_levels_offered": forms.Textarea(
                attrs={"rows": 3, "placeholder": "E.G. PP1–GRADE 9"}
            ),
            "streams_offered": forms.Textarea(
                attrs={"rows": 3, "placeholder": "E.G. GRADE 4: 4A, 4B, 4C"}
            ),
            "academic_year_start": forms.DateInput(attrs={"type": "date"}),
            "academic_year_end": forms.DateInput(attrs={"type": "date"}),
        }


class SchoolProfileOperationsForm(UppercaseFieldsMixin, forms.ModelForm):
    BOARDING_CHOICES = (
        ("DAY", "Day school"),
        ("BOARDING", "Boarding school"),
        ("BOTH", "Day and boarding"),
    )
    boarding_status = forms.ChoiceField(
        choices=BOARDING_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "uppercase-input"}),
    )
    uppercase_fields = ("boarding_facilities", "transport_routes")

    class Meta:
        model = SchoolProfile
        fields = (
            "enrollment_capacity", "boarding_status", "boarding_facilities",
            "transport_routes",
        )
        widgets = {
            "boarding_facilities": forms.Textarea(attrs={"rows": 4}),
            "transport_routes": forms.Textarea(
                attrs={"rows": 4, "placeholder": "ONE ROUTE PER LINE"}
            ),
        }
        labels = {"enrollment_capacity": "Total student enrollment capacity"}


class SchoolProfileFinancialForm(UppercaseFieldsMixin, forms.ModelForm):
    uppercase_fields = (
        "bank_details",
        "mpesa_paybill",
        "mpesa_till_number",
        "fee_schedule_reference",
    )

    class Meta:
        model = SchoolProfile
        fields = (
            "bank_details", "mpesa_paybill", "mpesa_till_number",
            "fee_schedule_reference",
        )
        widgets = {"bank_details": forms.Textarea(attrs={"rows": 4})}
        labels = {
            "mpesa_paybill": "M-Pesa Paybill number",
            "mpesa_till_number": "M-Pesa Till number",
            "fee_schedule_reference": "Fee schedule reference",
        }


class SchoolProfileComplianceForm(forms.ModelForm):
    class Meta:
        model = SchoolProfile
        fields = ("registration_certificate", "inspection_report")
        labels = {
            "registration_certificate": "Registration certificate",
            "inspection_report": "Recent inspection report",
        }


class EmployeeRegistrationForm(UserCreationForm):
    country_code = forms.ChoiceField(
        choices=[(item["iso"], f"{item['name']} (+{item['dial']})") for item in PHONE_COUNTRIES],
        initial="KE",
        label="Country",
    )

    class Meta:
        model = Employee
        fields = (
            "title",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "employee_code",
        )
        labels = {
            "employee_code": "Employment number",
        }
        widgets = {
            "title": forms.Select(attrs={"class": "uppercase-input"}),
            "first_name": forms.TextInput(attrs={"class": "uppercase-input"}),
            "last_name": forms.TextInput(attrs={"class": "uppercase-input"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "employee_code": forms.TextInput(
                attrs={
                    "inputmode": "numeric",
                    "placeholder": "SIX DIGITS",
                    "class": "uppercase-input",
                }
            ),
            "phone_number": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].help_text = ""
        self.fields["password2"].help_text = ""
        self.fields["password1"].widget.attrs.update(
            {"placeholder": "Min. 6 characters", "autocomplete": "new-password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"placeholder": "Repeat password", "autocomplete": "new-password"}
        )
        self.fields["phone_number"].required = False
        title_field = self.fields["title"]
        title_field.required = True
        title_field.empty_label = "Select title"
        title_field.choices = [("", "Select title"), *Employee.Title.choices]
        title_field.widget.attrs.update(
            {
                "required": "required",
                "aria-required": "true",
            }
        )

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip().upper()
        valid = {value for value, _label in Employee.Title.choices}
        if title not in valid:
            raise forms.ValidationError("Select a title (Mr., Mrs., Miss, etc.).")
        return title

    def clean_employee_code(self):
        return uppercase_value(self.cleaned_data["employee_code"])

    def clean_first_name(self):
        return uppercase_value(self.cleaned_data["first_name"])

    def clean_last_name(self):
        return uppercase_value(self.cleaned_data["last_name"])

    def clean(self):
        cleaned_data = super().clean()
        iso = cleaned_data.get("country_code") or "KE"
        country = country_by_iso(iso)
        phone = normalize_phone(self.data.get("phone_national", ""), country)
        if not phone:
            self.add_error("phone_number", "Enter a valid phone number.")
        else:
            cleaned_data["phone_number"] = phone
        return cleaned_data

    def save(self, commit=True):
        employee = super().save(commit=False)
        employee.role = Employee.Role.EMPLOYEE
        employee.approval_status = Employee.ApprovalStatus.PENDING_APPROVAL
        employee.is_active = False
        if commit:
            employee.save()
        return employee


class EmployeeProfileForm(UppercaseFieldsMixin, forms.ModelForm):
    uppercase_fields = ("first_name", "last_name", "employee_code")
    roles = forms.MultipleChoiceField(
        choices=Employee.Role.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Roles",
        help_text="Select every workspace role this employee should have.",
    )
    override_employment_number = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.HiddenInput,
    )

    class Meta:
        model = Employee
        fields = (
            "title",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "employee_code",
            "employment_number",
            "role",
            "approval_status",
        )
        labels = {
            "role": "Primary role",
            "employee_code": "Employment number",
            "employment_number": "Employee code",
        }
        help_texts = {
            "role": "Default workspace after sign-in when more than one role is assigned.",
        }
        widgets = {
            "title": forms.Select(attrs={"class": "uppercase-input"}),
            "first_name": forms.TextInput(attrs={"class": "uppercase-input"}),
            "last_name": forms.TextInput(attrs={"class": "uppercase-input"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "phone_number": forms.TextInput(attrs={"placeholder": "+2547XXXXXXXX"}),
            "employee_code": forms.TextInput(
                attrs={
                    "inputmode": "numeric",
                    "placeholder": "SIX DIGITS",
                    "class": "uppercase-input",
                }
            ),
            "employment_number": forms.NumberInput(
                attrs={
                    "min": "1",
                    "step": "1",
                    "placeholder": "E.G. 1",
                }
            ),
            "role": forms.Select(attrs={"class": "uppercase-input"}),
            "approval_status": forms.Select(attrs={"class": "uppercase-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employment_number"].required = True
        self.fields["employment_number"].min_value = 1
        title_field = self.fields["title"]
        title_field.required = True
        title_field.empty_label = "Select title"
        title_field.choices = [("", "Select title"), *Employee.Title.choices]
        title_field.widget.attrs.update({"required": "required", "aria-required": "true"})
        if self.instance and self.instance.pk:
            self.fields["roles"].initial = self.instance.role_values()
        elif self.instance and self.instance.role:
            self.fields["roles"].initial = [self.instance.role]

    def _override_requested(self):
        if not self.data:
            return False
        value = self.data.get("override_employment_number")
        if value is True:
            return True
        return str(value).lower() in ("1", "true", "on", "yes")

    def validate_unique(self):
        exclude = self._get_validation_exclusions()
        if self._override_requested():
            number = self.cleaned_data.get("employment_number")
            if number and self.instance.pk:
                conflict = (
                    Employee.objects.filter(employment_number=number)
                    .exclude(pk=self.instance.pk)
                    .first()
                )
                if conflict:
                    self._employment_number_conflict = conflict
                    exclude.add("employment_number")
        try:
            self.instance.validate_unique(exclude=exclude)
        except ValidationError as exc:
            self._update_errors(exc)

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip().upper()
        valid = {value for value, _label in Employee.Title.choices}
        if title not in valid:
            raise forms.ValidationError("Select a title (Mr., Mrs., Miss, etc.).")
        return title

    def clean_employment_number(self):
        number = self.cleaned_data.get("employment_number")
        if number is None or number < 1:
            raise forms.ValidationError("Enter a whole number starting from 1.")
        assigned = Employee.objects.filter(employment_number=number)
        if self.instance.pk:
            assigned = assigned.exclude(pk=self.instance.pk)
        already_issued = IssuedEmploymentNumber.objects.filter(number=number).exists()
        if (
            already_issued
            and self.instance.employment_number != number
            and not assigned.exists()
        ):
            raise forms.ValidationError(
                "This employee code has already been used and cannot be reused."
            )
        return number

    def clean(self):
        cleaned_data = super().clean()
        submitted_roles = cleaned_data.get("roles")
        roles_were_submitted = bool(self.data and "roles" in self.data)

        if roles_were_submitted:
            roles = submitted_roles or []
            if not roles:
                self.add_error("roles", "Select at least one role.")
        elif self.instance and self.instance.pk:
            roles = self.instance.role_values()
        elif cleaned_data.get("role"):
            roles = [cleaned_data["role"]]
        else:
            roles = []
            self.add_error("roles", "Select at least one role.")

        cleaned_data["roles"] = roles
        primary = cleaned_data.get("role")
        if roles and primary and primary not in roles:
            self.add_error(
                "role",
                "Primary role must be one of the selected roles.",
            )
        elif roles and not primary:
            cleaned_data["role"] = roles[0]

        number = cleaned_data.get("employment_number")
        override = self._override_requested()
        cleaned_data["override_employment_number"] = override
        if number and self.instance.pk:
            conflict = (
                Employee.objects.filter(employment_number=number)
                .exclude(pk=self.instance.pk)
                .first()
            )
            if conflict and not override:
                self.add_error(
                    "employment_number",
                    "This employee code is already assigned to another employee.",
                )
            elif conflict and override:
                self._employment_number_conflict = conflict
        return cleaned_data

    def save(self, commit=True):
        roles = self.cleaned_data.get("roles") or [self.instance.role]
        primary = self.cleaned_data.get("role") or roles[0]
        conflict = getattr(self, "_employment_number_conflict", None)
        override = self.cleaned_data.get("override_employment_number")
        number = self.cleaned_data.get("employment_number")
        if override and number and self.instance.pk and not conflict:
            conflict = (
                Employee.objects.filter(employment_number=number)
                .exclude(pk=self.instance.pk)
                .first()
            )

        def apply_roles(employee):
            if commit:
                employee.set_roles(roles, primary=primary)
            else:
                employee._pending_roles = roles
                employee._pending_primary_role = primary
            return employee

        if conflict:
            with transaction.atomic():
                Employee.objects.filter(pk=conflict.pk).update(employment_number=None)
                employee = super().save(commit=False)
                employee._allow_reassigned_employment_number = True
                if commit:
                    employee.save()
                return apply_roles(employee)

        with transaction.atomic():
            employee = super().save(commit=commit)
            return apply_roles(employee)


class EmployeeAccountSettingsForm(forms.ModelForm):
    country_code = forms.ChoiceField(
        choices=[(item["iso"], f"{item['name']} (+{item['dial']})") for item in PHONE_COUNTRIES],
        initial="KE",
        label="Country",
    )
    clear_profile_image = forms.BooleanField(required=False, label="Remove profile photo")

    class Meta:
        model = Employee
        fields = ("profile_image",)
        widgets = {
            "profile_image": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }
        labels = {
            "profile_image": "Profile photo",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        iso, _national = parse_stored_phone(getattr(self.instance, "phone_number", ""))
        self.fields["country_code"].initial = iso

    def clean(self):
        cleaned_data = super().clean()
        iso = cleaned_data.get("country_code") or "KE"
        country = country_by_iso(iso)
        phone = normalize_phone(self.data.get("phone_national", ""), country)
        if not phone:
            self.add_error("country_code", "Enter a valid phone number.")
        else:
            cleaned_data["phone_number"] = phone
        return cleaned_data

    def save(self, commit=True):
        employee = super().save(commit=False)
        employee.phone_number = self.cleaned_data["phone_number"]
        if self.cleaned_data.get("clear_profile_image"):
            if employee.profile_image:
                employee.profile_image.delete(save=False)
            employee.profile_image = None
        if commit:
            employee.save()
        return employee


class EmployeePasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].widget.attrs.update(
            {"placeholder": "Current password", "autocomplete": "current-password"}
        )
        self.fields["new_password1"].widget.attrs.update(
            {"placeholder": "New password", "autocomplete": "new-password"}
        )
        self.fields["new_password2"].widget.attrs.update(
            {"placeholder": "Confirm new password", "autocomplete": "new-password"}
        )
        self.fields["new_password1"].help_text = "Use at least 6 characters."
        self.fields["new_password2"].help_text = ""
