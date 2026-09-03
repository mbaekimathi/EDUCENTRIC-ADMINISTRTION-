from django import forms

from .models import ParentGuardian, Student


def uppercase_value(value):
    return value.strip().upper() if isinstance(value, str) else value


class StudentAdmissionForm(forms.Form):
    first_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "First name", "autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "Last name", "autocomplete": "family-name"}),
    )
    date_of_birth = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    gender = forms.ChoiceField(choices=Student.Gender.choices)
    academic_level = forms.ChoiceField(
        label="Class / level",
        choices=Student.AcademicLevel.choices,
    )
    assessment_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Optional"}),
    )
    previous_school = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Optional"}),
    )
    sponsorship_category = forms.ChoiceField(
        label="Sponsorship",
        choices=Student.SponsorshipCategory.choices,
    )
    sponsor_details = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Sponsor name and details"}),
        required=False,
    )
    parent_guardian_name = forms.CharField(
        max_length=200,
        label="Parent / guardian name",
        widget=forms.TextInput(attrs={"placeholder": "Full name", "autocomplete": "name"}),
    )
    relationship_to_student = forms.CharField(
        max_length=80,
        label="Relationship",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Mother, Father, Guardian"}),
    )
    parent_phone = forms.CharField(
        max_length=24,
        label="Phone",
        widget=forms.TextInput(attrs={"placeholder": "Phone number", "autocomplete": "tel"}),
    )
    parent_email = forms.EmailField(
        required=False,
        label="Email",
        widget=forms.EmailInput(attrs={"placeholder": "Optional", "autocomplete": "email"}),
    )
    home_address = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Optional"}),
        required=False,
    )
    medical_notes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Optional"}),
        required=False,
    )
    special_needs = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Optional"}),
        required=False,
    )
    emergency_contact = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Defaults to parent phone"}),
    )
    profile_image = forms.ImageField(
        required=False,
        label="Profile photo",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in {"parent_email", "date_of_birth", "profile_image"}:
                existing = field.widget.attrs.get("class", "")
                field.widget.attrs["class"] = f"{existing} uppercase-input".strip()
        self.fields["parent_email"].widget.attrs["autocomplete"] = "email"
        self.fields["parent_phone"].widget.attrs["autocomplete"] = "tel"

    def clean_assessment_number(self):
        number = uppercase_value(self.cleaned_data.get("assessment_number", ""))
        if not number:
            return None
        if Student.objects.filter(assessment_number=number).exists():
            raise forms.ValidationError("A student already uses this assessment number.")
        return number

    def clean_parent_phone(self):
        phone = uppercase_value(self.cleaned_data["parent_phone"])
        if len(phone.replace("+", "").replace(" ", "").replace("-", "")) < 7:
            raise forms.ValidationError("Enter a valid parent phone number.")
        return phone

    def clean(self):
        cleaned_data = super().clean()
        sponsored = cleaned_data.get("sponsorship_category")
        sponsor_details = cleaned_data.get("sponsor_details", "").strip()
        if sponsored in {
            Student.SponsorshipCategory.GOVERNMENT,
            Student.SponsorshipCategory.BOTH,
        } and not sponsor_details:
            self.add_error("sponsor_details", "Enter the sponsor details.")
        if not cleaned_data.get("emergency_contact"):
            cleaned_data["emergency_contact"] = cleaned_data.get("parent_phone", "")
        return cleaned_data

    def save(self):
        data = self.cleaned_data
        parent, created = ParentGuardian.objects.get_or_create(
            phone_number=data["parent_phone"],
            defaults={
                "full_name": uppercase_value(data["parent_guardian_name"]),
                "relationship_to_student": uppercase_value(data["relationship_to_student"]),
                "email": data["parent_email"],
            },
        )
        if not created:
            parent.full_name = uppercase_value(data["parent_guardian_name"])
            parent.relationship_to_student = uppercase_value(data["relationship_to_student"])
            parent.email = data["parent_email"]
            parent.save(update_fields=["full_name", "relationship_to_student", "email"])

        return Student.objects.create(
            first_name=uppercase_value(data["first_name"]),
            last_name=uppercase_value(data["last_name"]),
            date_of_birth=data["date_of_birth"],
            gender=data["gender"],
            academic_level=data["academic_level"],
            assessment_number=data.get("assessment_number") or None,
            previous_school=uppercase_value(data["previous_school"]),
            profile_image=data.get("profile_image"),
            sponsorship_category=data["sponsorship_category"],
            sponsor_details=uppercase_value(data["sponsor_details"]),
            parent_guardian=parent,
            home_address=uppercase_value(data["home_address"]),
            medical_notes=uppercase_value(data["medical_notes"]),
            special_needs=uppercase_value(data["special_needs"]),
            emergency_contact=uppercase_value(data["emergency_contact"]),
        )


class StudentWorkspaceForm(StudentAdmissionForm):
    admission_number = forms.CharField(
        max_length=40,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Optional"}),
    )
    class_group = forms.CharField(
        max_length=50,
        required=False,
        label="Class stream",
        widget=forms.TextInput(attrs={"placeholder": "e.g. 4X"}),
    )

    def __init__(self, *args, student=None, **kwargs):
        self.student = student
        super().__init__(*args, **kwargs)

    def clean_assessment_number(self):
        number = uppercase_value(self.cleaned_data.get("assessment_number", ""))
        if not number:
            return None
        existing = Student.objects.filter(assessment_number=number)
        if self.student is not None:
            existing = existing.exclude(pk=self.student.pk)
        if existing.exists():
            raise forms.ValidationError("A student already uses this assessment number.")
        return number

    def clean_admission_number(self):
        number = uppercase_value(self.cleaned_data.get("admission_number", ""))
        if not number:
            return ""
        existing = Student.objects.filter(admission_number=number)
        if self.student is not None:
            existing = existing.exclude(pk=self.student.pk)
        if existing.exists():
            raise forms.ValidationError("A student already uses this admission number.")
        return number

    def save(self):
        if self.student is None:
            raise ValueError("StudentWorkspaceForm requires a student instance.")
        data = self.cleaned_data
        parent, created = ParentGuardian.objects.get_or_create(
            phone_number=data["parent_phone"],
            defaults={
                "full_name": uppercase_value(data["parent_guardian_name"]),
                "relationship_to_student": uppercase_value(data["relationship_to_student"]),
                "email": data["parent_email"],
            },
        )
        if not created:
            parent.full_name = uppercase_value(data["parent_guardian_name"])
            parent.relationship_to_student = uppercase_value(data["relationship_to_student"])
            parent.email = data["parent_email"]
            parent.save(update_fields=["full_name", "relationship_to_student", "email"])

        self.student.first_name = uppercase_value(data["first_name"])
        self.student.last_name = uppercase_value(data["last_name"])
        self.student.date_of_birth = data["date_of_birth"]
        self.student.gender = data["gender"]
        self.student.academic_level = data["academic_level"]
        self.student.admission_number = data.get("admission_number") or None
        self.student.class_group = uppercase_value(data.get("class_group", ""))
        self.student.assessment_number = data.get("assessment_number") or None
        self.student.previous_school = uppercase_value(data["previous_school"])
        self.student.sponsorship_category = data["sponsorship_category"]
        self.student.sponsor_details = uppercase_value(data["sponsor_details"])
        self.student.parent_guardian = parent
        self.student.home_address = uppercase_value(data["home_address"])
        self.student.medical_notes = uppercase_value(data["medical_notes"])
        self.student.special_needs = uppercase_value(data["special_needs"])
        self.student.emergency_contact = uppercase_value(data["emergency_contact"])
        if data.get("profile_image"):
            self.student.profile_image = data["profile_image"]
        elif self.data.get("clear_profile_image") == "1":
            if self.student.profile_image:
                self.student.profile_image.delete(save=False)
            self.student.profile_image = None
        self.student.save()
        return self.student


class StudentLoginForm(forms.Form):
    assessment_number = forms.CharField(
        max_length=50,
        widget=forms.TextInput(
            attrs={
                "placeholder": "ENTER ASSESSMENT NUMBER",
                "class": "uppercase-input",
                "autocomplete": "username",
            }
        ),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter your password",
                "autocomplete": "current-password",
            }
        )
    )

    def clean(self):
        cleaned_data = super().clean()
        assessment_number = uppercase_value(cleaned_data.get("assessment_number"))
        password = cleaned_data.get("password")
        self.student = Student.objects.filter(assessment_number=assessment_number).first()
        if (
            not self.student
            or self.student.is_suspended
            or not self.student.is_active
            or not self.student.check_password(password)
        ):
            raise forms.ValidationError("Your assessment number or password is incorrect.")
        return cleaned_data

    def get_user(self):
        return getattr(self, "student", None)


class ParentLoginForm(forms.Form):
    phone_number = forms.CharField(
        max_length=24,
        widget=forms.TextInput(
            attrs={
                "placeholder": "ENTER PARENT PHONE",
                "class": "uppercase-input",
                "autocomplete": "tel",
            }
        ),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter your password",
                "autocomplete": "current-password",
            }
        )
    )

    def clean(self):
        cleaned_data = super().clean()
        phone_number = uppercase_value(cleaned_data.get("phone_number"))
        password = cleaned_data.get("password")
        self.parent = ParentGuardian.objects.filter(phone_number=phone_number).first()
        if not self.parent or not self.parent.is_active or not self.parent.check_password(password):
            raise forms.ValidationError("Your phone number or password is incorrect.")
        return cleaned_data

    def get_user(self):
        return getattr(self, "parent", None)
