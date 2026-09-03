from datetime import datetime

from django import forms
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Max

from pathlib import Path

from .models import (
    AcademicClass,
    AcademicLevel,
    AcademicTerm,
    AcademicYear,
    ELearningLearningMaterial,
    ELearningSubjectAllocation,
    ExamScheduleActivity,
    ExamScheduleProfile,
    GradeBand,
    LearningScheduleActivity,
    LearningScheduleProfile,
    LearningArea,
)


class AcademicLevelForm(forms.ModelForm):
    class Meta:
        model = AcademicLevel
        fields = ("name", "code", "category", "description", "order", "status")
        labels = {
            "name": "Level name",
            "code": "Level code",
            "category": "Level category",
            "description": "Description",
            "order": "Level order",
            "status": "Status",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "uppercase-input", "placeholder": "E.G. GRADE 1"}
            ),
            "code": forms.TextInput(
                attrs={"class": "uppercase-input", "placeholder": "E.G. G1"}
            ),
            "category": forms.TextInput(
                attrs={
                    "class": "uppercase-input",
                    "placeholder": "E.G. LOWER PRIMARY",
                    "list": "level-category-suggestions",
                    "autocomplete": "off",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "class": "uppercase-input",
                    "placeholder": "OPTIONAL NOTES",
                    "autocapitalize": "characters",
                }
            ),
            "order": forms.NumberInput(
                attrs={
                    "class": "uppercase-input",
                    "min": "0",
                    "step": "1",
                    "placeholder": "AUTO",
                }
            ),
            "status": forms.Select(attrs={"class": "uppercase-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].required = False
        if not self.instance.pk:
            self.fields["order"].help_text = "Leave blank to auto-assign the next order."
            if not self.is_bound:
                self.initial["order"] = None
                self.fields["order"].initial = None

    def clean_name(self):
        return self.cleaned_data["name"].strip().upper()

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()

    def clean_category(self):
        return self.cleaned_data["category"].strip().upper()

    def clean_description(self):
        return self.cleaned_data.get("description", "").strip().upper()

    def clean_order(self):
        order = self.cleaned_data.get("order")
        if order is None:
            if self.instance.pk:
                return self.instance.order
            return None
        if order < 0:
            raise ValidationError("Level order cannot be negative.")
        return order

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get("order") is None:
            next_order = (
                AcademicLevel.objects.aggregate(max_order=Max("order")).get("max_order") or 0
            ) + 1
            instance.order = next_order
        if commit:
            instance.save()
        return instance


class AcademicYearForm(forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ("start_date", "end_date", "is_current", "status")
        labels = {
            "start_date": "Start date",
            "end_date": "End date",
            "is_current": "Current academic year",
            "status": "Status",
        }
        widgets = {
            "start_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "end_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "is_current": forms.CheckboxInput(attrs={"class": "calendar-check"}),
            "status": forms.Select(attrs={"class": "uppercase-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("start_date", "end_date"):
            self.fields[field].input_formats = ["%Y-%m-%d"]

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        if start_date and end_date:
            self.instance.name = AcademicYear.name_from_dates(start_date, end_date)
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.name = AcademicYear.name_from_dates(instance.start_date, instance.end_date)
        instance.full_clean()
        if commit:
            instance.save()
        return instance


def parse_date_value(value):
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(f"{text} is not a valid date.")


def parse_academic_term_rows(post_data):
    ids = post_data.getlist("term_id")
    names = post_data.getlist("term_name")
    starts = post_data.getlist("term_start")
    ends = post_data.getlist("term_end")
    openings = post_data.getlist("term_opening")
    midterms = post_data.getlist("term_midterm")
    closings = post_data.getlist("term_closing")
    row_count = max(
        len(ids),
        len(names),
        len(starts),
        len(ends),
        len(openings),
        len(midterms),
        len(closings),
        0,
    )
    rows = []
    for index in range(row_count):
        name = (names[index] if index < len(names) else "").strip().upper()
        term_id = (ids[index] if index < len(ids) else "").strip()
        start_date = parse_date_value(starts[index] if index < len(starts) else "")
        end_date = parse_date_value(ends[index] if index < len(ends) else "")
        opening_date = parse_date_value(openings[index] if index < len(openings) else "")
        midterm_date = parse_date_value(midterms[index] if index < len(midterms) else "")
        closing_date = parse_date_value(closings[index] if index < len(closings) else "")
        if not any([start_date, end_date, opening_date, midterm_date, closing_date]):
            continue
        rows.append(
            {
                "id": int(term_id) if term_id.isdigit() else None,
                "name": name,
                "start_date": start_date,
                "end_date": end_date,
                "opening_date": opening_date,
                "midterm_date": midterm_date,
                "closing_date": closing_date,
            }
        )
    return rows


def validate_academic_term_rows(rows):
    errors = []
    seen_names = set()
    for index, row in enumerate(rows, start=1):
        label = row["name"] or f"Term {index}"
        if not row["name"]:
            errors.append(f"{label}: term name is required.")
        elif row["name"] in seen_names:
            errors.append(f"Term name {row['name']} is duplicated.")
        else:
            seen_names.add(row["name"])
        for field, caption in (
            ("start_date", "start date"),
            ("end_date", "end date"),
            ("opening_date", "opening date"),
            ("midterm_date", "midterm date"),
            ("closing_date", "closing date"),
        ):
            if not row[field]:
                errors.append(f"{label}: {caption} is required.")
    if errors:
        raise ValidationError(errors)
    return rows


def sync_academic_terms(academic_year, rows):
    validate_academic_term_rows(rows)
    keep_ids = [row["id"] for row in rows if row["id"]]
    AcademicTerm.objects.filter(academic_year=academic_year).exclude(pk__in=keep_ids).delete()

    try:
        for order, row in enumerate(rows, start=1):
            if row["id"]:
                term = AcademicTerm.objects.filter(
                    pk=row["id"], academic_year=academic_year
                ).first()
                if term is None:
                    raise ValidationError(f"Term id {row['id']} was not found for this academic year.")
            else:
                term = AcademicTerm(academic_year=academic_year)
            term.name = row["name"]
            term.start_date = row["start_date"]
            term.end_date = row["end_date"]
            term.opening_date = row["opening_date"]
            term.midterm_date = row["midterm_date"]
            term.closing_date = row["closing_date"]
            term.order = order
            term.full_clean()
            term.save()
    except IntegrityError:
        raise ValidationError("A term with this name already exists for this academic year.")
    return rows


class Html5TimeInput(forms.TimeInput):
    def __init__(self, attrs=None):
        super().__init__(format="%H:%M", attrs=attrs)
        self.input_type = "time"

    def format_value(self, value):
        if hasattr(value, "strftime"):
            return value.strftime("%H:%M")
        if isinstance(value, str) and len(value) >= 5:
            return value[:5]
        return super().format_value(value)


class ExamScheduleProfileForm(forms.ModelForm):
    class Meta:
        model = ExamScheduleProfile
        fields = (
            "name",
            "category",
            "academic_levels",
            "first_exam_start_time",
            "last_exam_end_time",
            "exam_session_duration_minutes",
        )
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "uppercase-input",
                    "readonly": True,
                    "placeholder": "AUTO-GENERATED FROM CATEGORY",
                    "data-schedule-name": "",
                }
            ),
            "category": forms.Select(
                attrs={
                    "class": "uppercase-input",
                    "data-schedule-category": "",
                }
            ),
            "academic_levels": forms.CheckboxSelectMultiple,
            "first_exam_start_time": Html5TimeInput(),
            "last_exam_end_time": Html5TimeInput(),
            "exam_session_duration_minutes": forms.TextInput(
                attrs={
                    "inputmode": "numeric",
                    "pattern": "[0-9]*",
                    "placeholder": "E.G. 120",
                    "autocomplete": "off",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        levels = AcademicLevel.objects.filter(
            status=AcademicLevel.Status.ACTIVE
        ).order_by("category", "order", "name")
        categories = (
            levels.exclude(category="")
            .values_list("category", flat=True)
            .distinct()
            .order_by("category")
        )
        self.fields["category"] = forms.ChoiceField(
            choices=[("", "Select academic category")]
            + [(category, category) for category in categories],
            label="Academic level category",
            widget=forms.Select(
                attrs={
                    "class": "uppercase-input",
                    "data-schedule-category": "",
                }
            ),
        )
        category_map = {str(level.pk): level.category for level in levels}
        self.fields["academic_levels"].widget = CategoryAwareCheckboxSelectMultiple(
            category_map=category_map
        )
        self.fields["academic_levels"].queryset = levels
        self.fields["name"].required = False
        self.fields["first_exam_start_time"].input_formats = ["%H:%M", "%H:%M:%S"]
        self.fields["last_exam_end_time"].input_formats = ["%H:%M", "%H:%M:%S"]
        if self.instance and self.instance.pk:
            if self.instance.category:
                self.fields["name"].initial = f"{self.instance.category} EXAM SESSION"
            if self.instance.first_exam_start_time:
                self.initial["first_exam_start_time"] = (
                    self.instance.first_exam_start_time.strftime("%H:%M")
                )
            if self.instance.last_exam_end_time:
                self.initial["last_exam_end_time"] = (
                    self.instance.last_exam_end_time.strftime("%H:%M")
                )

    def clean_category(self):
        return self.cleaned_data["category"].strip().upper()

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get("category", "")
        if category:
            cleaned["name"] = f"{category} EXAM SESSION"
        levels = cleaned.get("academic_levels")
        if category and levels is not None:
            mismatched = [level for level in levels if level.category != category]
            if mismatched:
                self.add_error(
                    "academic_levels",
                    "Select only academic levels in the chosen category.",
                )
        start = cleaned.get("first_exam_start_time")
        end = cleaned.get("last_exam_end_time")
        if start and end and end <= start:
            self.add_error(
                "last_exam_end_time",
                "Assessment end time must be later than first assessment start time.",
            )
        duration = cleaned.get("exam_session_duration_minutes")
        if duration is not None and duration <= 0:
            self.add_error(
                "exam_session_duration_minutes",
                "Assessment session duration must be greater than zero.",
            )
        return cleaned


class ExamScheduleActivityForm(forms.ModelForm):
    class Meta:
        model = ExamScheduleActivity
        fields = ("name", "start_time", "duration_minutes")
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "uppercase-input",
                    "placeholder": "E.G. MORNING BREAK",
                }
            ),
            "start_time": Html5TimeInput(),
            "duration_minutes": forms.TextInput(
                attrs={
                    "inputmode": "numeric",
                    "pattern": "[0-9]*",
                    "placeholder": "E.G. 30",
                    "autocomplete": "off",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_time"].input_formats = ["%H:%M", "%H:%M:%S"]

    def clean_name(self):
        return self.cleaned_data["name"].strip().upper()


ExamScheduleActivityFormSet = forms.modelformset_factory(
    ExamScheduleActivity,
    form=ExamScheduleActivityForm,
    extra=1,
    can_delete=True,
)


class CategoryAwareCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    def __init__(self, *args, category_map=None, **kwargs):
        self.category_map = category_map or {}
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        raw = getattr(value, "value", value)
        instance = getattr(value, "instance", None)
        category = self.category_map.get(str(raw), "")
        if not category and instance is not None:
            category = getattr(instance, "category", "") or ""
        if category:
            option["attrs"]["data-category"] = category
        return option


class LearningScheduleProfileForm(forms.ModelForm):
    study_days = forms.MultipleChoiceField(
        choices=LearningScheduleProfile.Weekday.choices,
        widget=forms.CheckboxSelectMultiple,
        label="Days studied",
    )

    class Meta:
        model = LearningScheduleProfile
        fields = (
            "name",
            "category",
            "academic_levels",
            "study_days",
            "lesson_duration_minutes",
            "first_class_start_time",
            "last_class_end_time",
        )
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "uppercase-input",
                    "readonly": True,
                    "placeholder": "AUTO-GENERATED FROM CATEGORY",
                    "data-schedule-name": "",
                }
            ),
            "category": forms.Select(
                attrs={
                    "class": "uppercase-input",
                    "data-schedule-category": "",
                }
            ),
            "academic_levels": forms.CheckboxSelectMultiple,
            "lesson_duration_minutes": forms.TextInput(
                attrs={
                    "inputmode": "numeric",
                    "pattern": "[0-9]*",
                    "placeholder": "E.G. 40",
                    "autocomplete": "off",
                }
            ),
            "first_class_start_time": Html5TimeInput(),
            "last_class_end_time": Html5TimeInput(),
        }

    def __init__(self, *args, **kwargs):
        self.schedule_kind = kwargs.pop(
            "schedule_kind",
            getattr(kwargs.get("instance"), "kind", None)
            or LearningScheduleProfile.Kind.LEARNING,
        )
        super().__init__(*args, **kwargs)
        if self.instance and not self.instance.pk:
            self.instance.kind = self.schedule_kind
        levels = AcademicLevel.objects.filter(
            status=AcademicLevel.Status.ACTIVE
        ).order_by("category", "order", "name")
        categories = (
            levels.exclude(category="")
            .values_list("category", flat=True)
            .distinct()
            .order_by("category")
        )
        self.fields["category"] = forms.ChoiceField(
            choices=[("", "Select academic category")]
            + [(category, category) for category in categories],
            label="Academic level category",
            widget=forms.Select(
                attrs={
                    "class": "uppercase-input",
                    "data-schedule-category": "",
                }
            ),
        )
        category_map = {str(level.pk): level.category for level in levels}
        self.fields["academic_levels"].widget = CategoryAwareCheckboxSelectMultiple(
            category_map=category_map
        )
        self.fields["academic_levels"].queryset = levels
        self.fields["name"].required = False
        self.fields["first_class_start_time"].input_formats = ["%H:%M", "%H:%M:%S"]
        self.fields["last_class_end_time"].input_formats = ["%H:%M", "%H:%M:%S"]
        if self.schedule_kind == LearningScheduleProfile.Kind.ELEARNING:
            self.fields["first_class_start_time"].label = "First session starts at"
            self.fields["last_class_end_time"].label = "Session end time"
            self.fields["lesson_duration_minutes"].label = "Session duration (minutes)"
            self.fields["study_days"].label = "Days studied"
        else:
            self.fields["first_class_start_time"].label = "First class starts at"
            self.fields["last_class_end_time"].label = "Lesson end time"
            self.fields["lesson_duration_minutes"].label = "Lesson duration (minutes)"
            self.fields["study_days"].label = "Days studied"
        if self.instance and self.instance.pk:
            if self.instance.category:
                self.fields["name"].initial = self._profile_name(self.instance.category)
            if self.instance.first_class_start_time:
                self.initial["first_class_start_time"] = (
                    self.instance.first_class_start_time.strftime("%H:%M")
                )
            if self.instance.last_class_end_time:
                self.initial["last_class_end_time"] = (
                    self.instance.last_class_end_time.strftime("%H:%M")
                )
            if self.instance.study_days:
                self.initial["study_days"] = list(self.instance.study_days)

    def _profile_name(self, category):
        if self.schedule_kind == LearningScheduleProfile.Kind.ELEARNING:
            return f"{category} E-LEARNING SESSION"
        return f"{category} SESSION"

    def clean_category(self):
        return self.cleaned_data["category"].strip().upper()

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get("category", "")
        if category:
            cleaned["name"] = self._profile_name(category)
        cleaned["kind"] = self.schedule_kind
        levels = cleaned.get("academic_levels")
        if category and levels is not None:
            mismatched = [level for level in levels if level.category != category]
            if mismatched:
                self.add_error(
                    "academic_levels",
                    "Select only academic levels in the chosen category.",
                )
        start = cleaned.get("first_class_start_time")
        end = cleaned.get("last_class_end_time")
        if start and end and end <= start:
            end_label = (
                "Session end time"
                if self.schedule_kind == LearningScheduleProfile.Kind.ELEARNING
                else "Lesson end time"
            )
            start_label = (
                "first session start time"
                if self.schedule_kind == LearningScheduleProfile.Kind.ELEARNING
                else "first class start time"
            )
            self.add_error(
                "last_class_end_time",
                f"{end_label} must be later than {start_label}.",
            )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.kind = self.schedule_kind
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class LearningScheduleActivityForm(forms.ModelForm):
    class Meta:
        model = LearningScheduleActivity
        fields = ("name", "start_time", "duration_minutes")
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "uppercase-input",
                    "placeholder": "E.G. MORNING BREAK",
                }
            ),
            "start_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "duration_minutes": forms.TextInput(
                attrs={
                    "inputmode": "numeric",
                    "pattern": "[0-9]*",
                    "placeholder": "E.G. 30",
                    "autocomplete": "off",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_time"].input_formats = ["%H:%M", "%H:%M:%S"]

    def clean_name(self):
        return self.cleaned_data["name"].strip().upper()


LearningScheduleActivityFormSet = forms.modelformset_factory(
    LearningScheduleActivity,
    form=LearningScheduleActivityForm,
    extra=1,
    can_delete=True,
)


def parse_academic_class_rows(post_data):
    """Parse class rows posted with a level register/edit form."""
    ids = post_data.getlist("class_id")
    names = post_data.getlist("class_name")
    codes = post_data.getlist("class_code")
    statuses = post_data.getlist("class_status")
    row_count = max(len(names), len(codes), len(statuses), len(ids))
    rows = []
    for index in range(row_count):
        name = (names[index] if index < len(names) else "").strip().upper()
        code = (codes[index] if index < len(codes) else "").strip().upper()
        status = (statuses[index] if index < len(statuses) else AcademicClass.Status.ACTIVE).strip().upper()
        class_id = (ids[index] if index < len(ids) else "").strip()
        if not name and not code:
            continue
        rows.append(
            {
                "id": int(class_id) if class_id.isdigit() else None,
                "name": name,
                "code": code,
                "status": status if status in AcademicClass.Status.values else AcademicClass.Status.ACTIVE,
            }
        )
    return rows


def validate_academic_class_rows(rows):
    errors = []
    seen_codes = set()
    for index, row in enumerate(rows, start=1):
        if not row["name"]:
            errors.append(f"Class {index}: name is required.")
        if not row["code"]:
            errors.append(f"Class {index}: code is required.")
        elif row["code"] in seen_codes:
            errors.append(f"Class code {row['code']} is duplicated.")
        else:
            seen_codes.add(row["code"])
    if errors:
        raise ValidationError(errors)
    return rows


def sync_academic_classes(level, rows):
    """Create/update submitted classes and delete removed ones for a level."""
    validate_academic_class_rows(rows)
    keep_ids = [row["id"] for row in rows if row["id"]]
    AcademicClass.objects.filter(academic_level=level).exclude(pk__in=keep_ids).delete()

    saved_ids = []
    try:
        for order, row in enumerate(rows, start=1):
            if row["id"]:
                academic_class = AcademicClass.objects.filter(
                    pk=row["id"], academic_level=level
                ).first()
                if academic_class is None:
                    raise ValidationError(f"Class id {row['id']} was not found for this level.")
                academic_class.name = row["name"]
                academic_class.code = row["code"]
                academic_class.status = row["status"]
                academic_class.order = order
                academic_class.save()
                saved_ids.append(academic_class.id)
            else:
                academic_class = AcademicClass.objects.create(
                    academic_level=level,
                    name=row["name"],
                    code=row["code"],
                    status=row["status"],
                    order=order,
                )
                saved_ids.append(academic_class.id)
    except IntegrityError:
        raise ValidationError(
            "A class with this code already exists for this academic level."
        )
    return saved_ids


class AcademicClassForm(forms.ModelForm):
    class Meta:
        model = AcademicClass
        fields = ("name", "code", "status")
        labels = {
            "name": "Class name",
            "code": "Class code",
            "status": "Status",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "uppercase-input", "placeholder": "E.G. X"}
            ),
            "code": forms.TextInput(
                attrs={"class": "uppercase-input", "placeholder": "E.G. G1X"}
            ),
            "status": forms.Select(attrs={"class": "uppercase-input"}),
        }

    def __init__(self, *args, academic_level=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.academic_level = academic_level or getattr(self.instance, "academic_level", None)

    def clean_name(self):
        return self.cleaned_data["name"].strip().upper()

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if self.academic_level is not None:
            qs = AcademicClass.objects.filter(academic_level=self.academic_level, code=code)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError(
                    "A class with this code already exists for this academic level."
                )
        return code

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.academic_level is not None:
            instance.academic_level = self.academic_level
        if instance.pk is None:
            next_order = (
                AcademicClass.objects.filter(academic_level=instance.academic_level)
                .aggregate(max_order=Max("order"))
                .get("max_order")
                or 0
            ) + 1
            instance.order = next_order
        if commit:
            instance.save()
        return instance


class LearningAreaForm(forms.ModelForm):
    class Meta:
        model = LearningArea
        fields = ("academic_levels", "name", "code", "description", "status")
        labels = {
            "academic_levels": "Academic levels",
            "name": "Learning area name",
            "code": "Code",
            "description": "Description",
            "status": "Status",
        }
        widgets = {
            "academic_levels": forms.CheckboxSelectMultiple(),
            "name": forms.TextInput(
                attrs={"class": "uppercase-input", "placeholder": "E.G. MATHEMATICS"}
            ),
            "code": forms.TextInput(
                attrs={"class": "uppercase-input", "placeholder": "E.G. MATH"}
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "class": "uppercase-input",
                    "placeholder": "OPTIONAL NOTES",
                    "autocapitalize": "characters",
                }
            ),
            "status": forms.Select(attrs={"class": "uppercase-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        levels = AcademicLevel.objects.order_by("order", "name")
        self.fields["academic_levels"].queryset = levels
        self.fields["academic_levels"].required = True
        self.fields["academic_levels"].label_from_instance = (
            lambda obj: f"{obj.name} ({obj.code})"
        )
        if not levels.exists():
            self.fields["academic_levels"].help_text = (
                "Register an academic level first under Curriculum → Academic levels."
            )
        else:
            self.fields["academic_levels"].help_text = (
                "Select one or more academic levels this learning area belongs to."
            )

    def clean_name(self):
        return self.cleaned_data["name"].strip().upper()

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()

    def clean_description(self):
        return self.cleaned_data.get("description", "").strip().upper()

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.pk is None:
            next_order = (
                LearningArea.objects.aggregate(max_order=Max("display_order")).get("max_order")
                or 0
            ) + 1
            instance.display_order = next_order
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class GradeBandForm(forms.ModelForm):
    class Meta:
        model = GradeBand
        fields = (
            "code",
            "mark_level",
            "meaning",
            "points",
            "start_percent",
            "end_percent",
        )
        labels = {
            "code": "Code",
            "mark_level": "Mark level",
            "meaning": "Meaning",
            "points": "Points",
            "start_percent": "Start %",
            "end_percent": "End %",
        }
        widgets = {
            "code": forms.TextInput(
                attrs={"class": "uppercase-input", "placeholder": "E.G. EE1"}
            ),
            "mark_level": forms.TextInput(
                attrs={
                    "class": "uppercase-input",
                    "placeholder": "E.G. EXCEEDING EXPECTATION 1",
                }
            ),
            "meaning": forms.TextInput(
                attrs={"class": "uppercase-input", "placeholder": "E.G. EXCELLENT"}
            ),
            "points": forms.NumberInput(
                attrs={"min": "0", "max": "100", "step": "1", "placeholder": "8"}
            ),
            "start_percent": forms.NumberInput(
                attrs={"min": "0", "max": "100", "step": "1", "placeholder": "91"}
            ),
            "end_percent": forms.NumberInput(
                attrs={"min": "0", "max": "100", "step": "1", "placeholder": "100"}
            ),
        }

    def __init__(self, *args, academic_level=None, **kwargs):
        self.academic_level = academic_level
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.academic_level_id:
            self.academic_level = self.instance.academic_level

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        queryset = GradeBand.objects.filter(code=code, academic_level=self.academic_level)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            scope = (
                self.academic_level.name
                if self.academic_level is not None
                else "the default grading system"
            )
            raise forms.ValidationError(f"Code {code} already exists for {scope}.")
        return code

    def clean_mark_level(self):
        return self.cleaned_data["mark_level"].strip().upper()

    def clean_meaning(self):
        return self.cleaned_data["meaning"].strip().upper()

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start_percent")
        end = cleaned_data.get("end_percent")
        if start is not None and end is not None and end < start:
            self.add_error("end_percent", "End % must be at or above start %.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.academic_level = self.academic_level
        if commit:
            instance.save()
        return instance


class ELearningLearningMaterialForm(forms.ModelForm):
    """Register portal-ready e-learning materials with format-specific file rules."""

    class Meta:
        model = ELearningLearningMaterial
        fields = (
            "allocation",
            "content_format",
            "category",
            "name",
            "description",
            "cover_image",
            "material_file",
        )
        labels = {
            "allocation": "E-learning subject",
            "content_format": "Material format",
            "category": "Category",
            "name": "Material name",
            "description": "Description",
            "cover_image": "Cover image",
            "material_file": "Upload file",
        }
        widgets = {
            "allocation": forms.Select(),
            "content_format": forms.Select(),
            "category": forms.TextInput(
                attrs={
                    "placeholder": "e.g. Week 3",
                    "list": "material-category-suggestions",
                    "autocomplete": "off",
                }
            ),
            "name": forms.TextInput(attrs={"placeholder": "Material title"}),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Optional short note",
                }
            ),
            "cover_image": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "material_file": forms.ClearableFileInput(),
        }
        help_texts = {
            "content_format": "",
            "cover_image": "",
            "material_file": "",
        }

    def __init__(self, *args, allocations=None, **kwargs):
        super().__init__(*args, **kwargs)
        if allocations is None:
            qs = ELearningSubjectAllocation.objects.none()
        elif hasattr(allocations, "select_related"):
            qs = allocations.select_related("academic_level", "learning_area")
        else:
            ids = [getattr(item, "pk", item) for item in allocations]
            qs = ELearningSubjectAllocation.objects.filter(pk__in=ids).select_related(
                "academic_level", "learning_area"
            )
        self.fields["allocation"].queryset = qs
        self.fields["allocation"].label_from_instance = (
            lambda item: f"{item.academic_level.code} · {item.learning_area.code} — {item.learning_area.name}"
        )
        for name in self.fields:
            css = self.fields[name].widget.attrs.get("class", "")
            self.fields[name].widget.attrs["class"] = f"{css} uppercase-input".strip()
        self.fields["description"].widget.attrs["class"] = (
            self.fields["description"].widget.attrs.get("class", "").replace("uppercase-input", "").strip()
        )
        self.fields["name"].widget.attrs["class"] = (
            self.fields["name"].widget.attrs.get("class", "").replace("uppercase-input", "").strip()
        )
        self.fields["category"].widget.attrs["class"] = (
            self.fields["category"].widget.attrs.get("class", "").replace("uppercase-input", "").strip()
        )
        format_value = None
        if self.is_bound:
            format_value = self.data.get("content_format")
        elif self.instance and self.instance.pk:
            format_value = self.instance.content_format
        accept = self._accept_for_format(format_value)
        if accept:
            self.fields["material_file"].widget.attrs["accept"] = accept

    @staticmethod
    def _accept_for_format(content_format):
        extensions = ELearningLearningMaterial.FORMAT_EXTENSIONS.get(content_format, ())
        if not extensions:
            return ".pdf,.mp4,.pptx,.zip,.mp3"
        return ",".join(extensions)

    def clean_category(self):
        return (self.cleaned_data.get("category") or "").strip()

    def clean_name(self):
        return (self.cleaned_data.get("name") or "").strip()

    def clean_description(self):
        return (self.cleaned_data.get("description") or "").strip()

    def clean(self):
        cleaned = super().clean()
        content_format = cleaned.get("content_format")
        material_file = cleaned.get("material_file")
        if not content_format or not material_file:
            return cleaned
        allowed = ELearningLearningMaterial.FORMAT_EXTENSIONS.get(content_format, ())
        ext = Path(getattr(material_file, "name", "")).suffix.lower()
        if allowed and ext not in allowed:
            labels = ", ".join(allowed)
            self.add_error(
                "material_file",
                f"For {dict(ELearningLearningMaterial.ContentFormat.choices).get(content_format)}, "
                f"upload {labels} only.",
            )
        max_bytes = {
            ELearningLearningMaterial.ContentFormat.NOTES: 40 * 1024 * 1024,
            ELearningLearningMaterial.ContentFormat.LECTURE_VIDEO: 500 * 1024 * 1024,
            ELearningLearningMaterial.ContentFormat.SLIDES: 80 * 1024 * 1024,
            ELearningLearningMaterial.ContentFormat.QUIZ_SCORM: 200 * 1024 * 1024,
            ELearningLearningMaterial.ContentFormat.AUDIO: 80 * 1024 * 1024,
        }.get(content_format, 100 * 1024 * 1024)
        try:
            size = material_file.size
        except (OSError, ValueError, AttributeError):
            size = 0
        if size and size > max_bytes:
            self.add_error(
                "material_file",
                f"File is too large for portal download. Keep under {max_bytes // (1024 * 1024)} MB.",
            )
        return cleaned

    def save(self, commit=True, uploaded_by=None):
        instance = super().save(commit=False)
        instance.sync_file_metadata()
        instance.is_published = True
        if uploaded_by is not None:
            instance.uploaded_by = uploaded_by
        if commit:
            instance.save()
        return instance
