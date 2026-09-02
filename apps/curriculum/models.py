from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
import re

class AcademicLevel(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "ACTIVE"
        INACTIVE = "INACTIVE", "INACTIVE"

    name = models.CharField("level name", max_length=120)
    code = models.CharField("level code", max_length=40, unique=True)
    category = models.CharField("level category", max_length=120)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField("level order", default=0)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "academic level"
        verbose_name_plural = "academic levels"

    def __str__(self):
        return f"{self.name} ({self.code})"


class AcademicClass(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "ACTIVE"
        INACTIVE = "INACTIVE", "INACTIVE"

    academic_level = models.ForeignKey(
        AcademicLevel,
        on_delete=models.CASCADE,
        related_name="classes",
        verbose_name="academic level",
    )
    name = models.CharField("class name", max_length=120)
    code = models.CharField("class code", max_length=40)
    order = models.PositiveIntegerField("class order", default=0)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    class_teacher = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_classes",
        limit_choices_to={"assigned_roles__role": "TEACHER"},
        verbose_name="class teacher",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["academic_level", "order", "name"]
        verbose_name = "academic class"
        verbose_name_plural = "academic classes"
        constraints = [
            models.UniqueConstraint(
                fields=["academic_level", "code"],
                name="unique_class_code_per_academic_level",
            ),
        ]

    def clean(self):
        if self.class_teacher_id and not self.class_teacher.has_role("TEACHER"):
            raise ValidationError(
                {"class_teacher": "Only employees with the teacher role can be allocated as class teachers."}
            )

    def __str__(self):
        return f"{self.academic_level.code}: {self.name} ({self.code})"

    @property
    def display_label(self):
        """Human label such as 8X when the stored name is only the stream."""
        name = (self.name or "").strip()
        code = (self.code or "").strip()
        level = getattr(self, "academic_level", None)
        if not level:
            return name or code
        level_code = (level.code or "").strip()
        level_name = (level.name or "").strip()
        digits = re.search(r"(\d+)", level_code) or re.search(r"(\d+)", level_name)
        if digits and name:
            digit = digits.group(1)
            if digit not in name:
                compact = re.sub(r"\s+", "", name)
                if len(compact) <= 2:
                    return f"{digit}{compact}"
                return f"{digit} {name}"
        if name:
            return name
        if code:
            return code
        return level_name


class AcademicYear(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "ACTIVE"
        INACTIVE = "INACTIVE", "INACTIVE"

    name = models.CharField("academic year", max_length=40, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField("current academic year", default=False)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "name"]
        verbose_name = "academic year"
        verbose_name_plural = "academic years"

    @staticmethod
    def name_from_dates(start_date, end_date):
        if not start_date or not end_date:
            return ""
        if start_date.year == end_date.year:
            return str(start_date.year)
        return f"{start_date.year}/{end_date.year}"

    def clean(self):
        if self.start_date and self.end_date:
            self.name = self.name_from_dates(self.start_date, self.end_date)
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Academic year end date must be on or after the start date."})
        if self.start_date and self.end_date:
            overlapping = AcademicYear.objects.filter(
                start_date__lte=self.end_date,
                end_date__gte=self.start_date,
            )
            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)
            overlap = overlapping.first()
            if overlap:
                raise ValidationError(
                    f"This academic year overlaps {overlap.name} ({overlap.start_date} to {overlap.end_date})."
                )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_current:
            AcademicYear.objects.exclude(pk=self.pk).filter(is_current=True).update(is_current=False)

    def __str__(self):
        return self.name


class AcademicTerm(models.Model):
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
        related_name="terms",
        verbose_name="academic year",
    )
    name = models.CharField("term name", max_length=80)
    start_date = models.DateField()
    end_date = models.DateField()
    opening_date = models.DateField("opening date")
    midterm_date = models.DateField("midterm date")
    closing_date = models.DateField("closing date")
    order = models.PositiveIntegerField("term order", default=0)
    is_current = models.BooleanField("current academic term", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["academic_year", "order", "start_date", "name"]
        verbose_name = "academic term"
        verbose_name_plural = "academic terms"
        constraints = [
            models.UniqueConstraint(
                fields=["academic_year", "name"],
                name="unique_term_name_per_academic_year",
            ),
        ]

    def clean(self):
        errors = {}
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors["end_date"] = "Term end date must be on or after the start date."

        year = self.academic_year
        if year and self.start_date and self.end_date:
            if self.start_date < year.start_date or self.end_date > year.end_date:
                errors["start_date"] = "Term dates must fall within the academic year."

        milestone_dates = (
            ("opening_date", self.opening_date, "Opening date"),
            ("midterm_date", self.midterm_date, "Midterm date"),
            ("closing_date", self.closing_date, "Closing date"),
        )
        if self.start_date and self.end_date:
            for field, value, label in milestone_dates:
                if value and (value < self.start_date or value > self.end_date):
                    errors[field] = f"{label} must fall within the term dates."

        if self.opening_date and self.midterm_date and self.midterm_date < self.opening_date:
            errors["midterm_date"] = "Midterm date must be on or after the opening date."
        if self.midterm_date and self.closing_date and self.closing_date < self.midterm_date:
            errors["closing_date"] = "Closing date must be on or after the midterm date."
        if self.opening_date and self.closing_date and self.closing_date < self.opening_date:
            errors["closing_date"] = "Closing date must be on or after the opening date."

        if year and self.start_date and self.end_date:
            overlapping = AcademicTerm.objects.filter(academic_year=year).filter(
                Q(start_date__lte=self.end_date) & Q(end_date__gte=self.start_date)
            )
            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)
            overlap = overlapping.first()
            if overlap:
                errors["start_date"] = (
                    f"This term overlaps {overlap.name} ({overlap.start_date} to {overlap.end_date})."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_current:
            AcademicTerm.objects.exclude(pk=self.pk).filter(is_current=True).update(is_current=False)

    def __str__(self):
        return f"{self.academic_year}: {self.name}"


class LearningArea(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "ACTIVE"
        INACTIVE = "INACTIVE", "INACTIVE"

    academic_levels = models.ManyToManyField(
        AcademicLevel,
        related_name="learning_areas",
        verbose_name="academic levels",
    )
    name = models.CharField("learning area name", max_length=120)
    code = models.CharField(max_length=40, unique=True)
    description = models.TextField(blank=True)
    total_marks = models.PositiveIntegerField(
        "total marks",
        default=100,
    )
    display_order = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name"]
        verbose_name = "learning area"
        verbose_name_plural = "learning areas"

    def __str__(self):
        return f"{self.name} ({self.code})"


class ClassSubjectAllocation(models.Model):
    academic_class = models.ForeignKey(
        AcademicClass,
        on_delete=models.CASCADE,
        related_name="subject_allocations",
        verbose_name="class",
    )
    learning_area = models.ForeignKey(
        LearningArea,
        on_delete=models.CASCADE,
        related_name="class_allocations",
        verbose_name="subject",
    )
    teacher = models.ForeignKey(
        "employees.Employee",
        on_delete=models.CASCADE,
        related_name="subject_allocations",
        limit_choices_to={"assigned_roles__role": "TEACHER"},
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "academic_class__academic_level__order",
            "academic_class__order",
            "learning_area__display_order",
            "learning_area__name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_class", "learning_area"],
                name="unique_teacher_allocation_per_class_and_subject",
            ),
        ]
        verbose_name = "class subject allocation"
        verbose_name_plural = "class subject allocations"

    def clean(self):
        if self.teacher_id and not self.teacher.has_role("TEACHER"):
            raise ValidationError({"teacher": "Only employees with the teacher role can be allocated a subject."})
        if (
            self.academic_class_id
            and self.learning_area_id
            and not self.learning_area.academic_levels.filter(pk=self.academic_class.academic_level_id).exists()
        ):
            raise ValidationError(
                {"learning_area": "This subject is not linked to the academic level of the selected class."}
            )

    def __str__(self):
        return f"{self.academic_class}: {self.learning_area.code} → {self.teacher}"


class ELearningSubjectAllocation(models.Model):
    academic_level = models.ForeignKey(
        AcademicLevel,
        on_delete=models.CASCADE,
        related_name="elearning_subject_allocations",
        verbose_name="academic level",
    )
    learning_area = models.ForeignKey(
        LearningArea,
        on_delete=models.CASCADE,
        related_name="elearning_allocations",
        verbose_name="subject",
    )
    teacher = models.ForeignKey(
        "employees.Employee",
        on_delete=models.CASCADE,
        related_name="elearning_subject_allocations",
        limit_choices_to={"assigned_roles__role": "TEACHER"},
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "academic_level__order",
            "learning_area__display_order",
            "learning_area__name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_level", "learning_area"],
                name="unique_elearning_teacher_per_level_and_subject",
            ),
        ]
        verbose_name = "e-learning subject allocation"
        verbose_name_plural = "e-learning subject allocations"

    def clean(self):
        if self.teacher_id and not self.teacher.has_role("TEACHER"):
            raise ValidationError({"teacher": "Only employees with the teacher role can be allocated a subject."})
        if (
            self.academic_level_id
            and self.learning_area_id
            and not self.learning_area.academic_levels.filter(pk=self.academic_level_id).exists()
        ):
            raise ValidationError(
                {"learning_area": "This subject is not linked to the selected academic level."}
            )

    def __str__(self):
        return f"{self.academic_level}: {self.learning_area.code} → {self.teacher}"


class ExamSupervisorAllocation(models.Model):
    academic_class = models.ForeignKey(
        AcademicClass,
        on_delete=models.CASCADE,
        related_name="exam_supervisor_allocations",
        verbose_name="class",
    )
    learning_area = models.ForeignKey(
        LearningArea,
        on_delete=models.CASCADE,
        related_name="exam_supervisor_allocations",
        verbose_name="subject",
    )
    supervisor = models.ForeignKey(
        "employees.Employee",
        on_delete=models.CASCADE,
        related_name="exam_supervisor_allocations",
        limit_choices_to={"assigned_roles__role": "TEACHER"},
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "academic_class__academic_level__order",
            "academic_class__order",
            "learning_area__display_order",
            "learning_area__name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_class", "learning_area"],
                name="unique_supervisor_allocation_per_class_and_subject",
            ),
        ]
        verbose_name = "assessment supervisor allocation"
        verbose_name_plural = "assessment supervisor allocations"

    def clean(self):
        if self.supervisor_id and not self.supervisor.has_role("TEACHER"):
            raise ValidationError(
                {"supervisor": "Only employees with the teacher role can be allocated as assessment supervisors."}
            )
        if (
            self.academic_class_id
            and self.learning_area_id
            and not self.learning_area.academic_levels.filter(pk=self.academic_class.academic_level_id).exists()
        ):
            raise ValidationError(
                {"learning_area": "This subject is not linked to the academic level of the selected class."}
            )

    def __str__(self):
        return f"{self.academic_class}: {self.learning_area.code} → {self.supervisor}"


class ExamSubjectSetting(models.Model):
    academic_level = models.ForeignKey(
        AcademicLevel,
        on_delete=models.CASCADE,
        related_name="exam_subject_settings",
    )
    learning_area = models.ForeignKey(
        LearningArea,
        on_delete=models.CASCADE,
        related_name="exam_settings",
    )
    out_of_marks = models.PositiveIntegerField(
        "out of marks",
        default=100,
    )
    display_order = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "academic_level__order",
            "display_order",
            "learning_area__display_order",
            "learning_area__name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_level", "learning_area"],
                name="unique_exam_setting_per_level_and_learning_area",
            ),
        ]
        verbose_name = "assessment subject setting"
        verbose_name_plural = "assessment subject settings"

    def __str__(self):
        return f"{self.academic_level.code}: {self.learning_area.code} / {self.out_of_marks}"


class CombinedExamSubject(models.Model):
    academic_level = models.ForeignKey(
        AcademicLevel,
        on_delete=models.CASCADE,
        related_name="combined_exam_subjects",
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=40)
    subjects = models.ManyToManyField(
        ExamSubjectSetting,
        through="CombinedExamSubjectComponent",
        related_name="combined_subjects",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["academic_level__order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_level", "code"],
                name="unique_combined_exam_subject_code_per_level",
            ),
        ]
        verbose_name = "combined assessment subject"
        verbose_name_plural = "combined assessment subjects"

    @property
    def out_of_marks(self):
        return sum(
            (component.subject_setting.out_of_marks for component in self.components.all()),
            start=0,
        )

    @property
    def component_codes(self):
        return " + ".join(
            component.subject_setting.learning_area.code
            for component in self.components.all()
        )

    def __str__(self):
        return f"{self.academic_level.code}: {self.name} ({self.code})"


class CombinedExamSubjectComponent(models.Model):
    combined_subject = models.ForeignKey(
        CombinedExamSubject,
        on_delete=models.CASCADE,
        related_name="components",
    )
    subject_setting = models.ForeignKey(
        ExamSubjectSetting,
        on_delete=models.CASCADE,
        related_name="combined_components",
    )
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["combined_subject", "subject_setting"],
                name="unique_component_per_combined_exam_subject",
            ),
        ]
        verbose_name = "combined assessment subject component"
        verbose_name_plural = "combined assessment subject components"

    def __str__(self):
        return (
            f"{self.combined_subject.code}: "
            f"{self.subject_setting.learning_area.code} ({self.position})"
        )


class ExamScheduleProfile(models.Model):
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=120)
    academic_levels = models.ManyToManyField(
        AcademicLevel,
        related_name="exam_schedule_profiles",
    )
    first_exam_start_time = models.TimeField("first assessment starts at")
    last_exam_end_time = models.TimeField("assessment end time")
    exam_session_duration_minutes = models.PositiveIntegerField(
        "assessment session duration (minutes)",
        default=120,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "category"],
                name="unique_exam_schedule_profile_per_category",
            ),
        ]
        verbose_name = "assessment schedule profile"
        verbose_name_plural = "assessment schedule profiles"

    def clean(self):
        super().clean()
        if self.exam_session_duration_minutes <= 0:
            raise ValidationError(
                {
                    "exam_session_duration_minutes": "Assessment session duration must be greater than zero."
                }
            )
        if (
            self.first_exam_start_time
            and self.last_exam_end_time
            and self.last_exam_end_time <= self.first_exam_start_time
        ):
            raise ValidationError(
                {
                    "last_exam_end_time": "Assessment end time must be later than first assessment start time."
                }
            )

    def __str__(self):
        return f"{self.category}: {self.name}"


class ExamScheduleActivity(models.Model):
    profile = models.ForeignKey(
        ExamScheduleProfile,
        on_delete=models.CASCADE,
        related_name="activities",
    )
    name = models.CharField(max_length=120)
    start_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["start_time", "order", "name"]
        verbose_name = "assessment schedule activity"
        verbose_name_plural = "assessment schedule activities"

    @property
    def end_time(self):
        total_minutes = self.start_time.hour * 60 + self.start_time.minute
        total_minutes += self.duration_minutes
        total_minutes %= 24 * 60
        return self.start_time.replace(
            hour=total_minutes // 60,
            minute=total_minutes % 60,
        )

    def __str__(self):
        return f"{self.profile}: {self.name}"


class ExamTimetableSession(models.Model):
    profile = models.ForeignKey(
        ExamScheduleProfile,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    name = models.CharField(max_length=120)
    start_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField()
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_time", "order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "name"],
                name="unique_exam_session_name_per_profile",
            ),
        ]
        verbose_name = "assessment timetable session"
        verbose_name_plural = "assessment timetable sessions"

    def clean(self):
        super().clean()
        if self.duration_minutes <= 0:
            raise ValidationError(
                {"duration_minutes": "Duration must be greater than zero."}
            )

    @property
    def end_time(self):
        total_minutes = self.start_time.hour * 60 + self.start_time.minute
        total_minutes += self.duration_minutes
        total_minutes %= 24 * 60
        return self.start_time.replace(
            hour=total_minutes // 60,
            minute=total_minutes % 60,
        )

    @property
    def duration_label(self):
        hours, mins = divmod(self.duration_minutes, 60)
        if hours and mins:
            return f"{hours}h {mins}m"
        if hours:
            return f"{hours}h"
        return f"{mins}m"

    def __str__(self):
        return f"{self.profile}: {self.name}"


class LearningScheduleProfile(models.Model):
    class Weekday(models.TextChoices):
        MONDAY = "MON", "Monday"
        TUESDAY = "TUE", "Tuesday"
        WEDNESDAY = "WED", "Wednesday"
        THURSDAY = "THU", "Thursday"
        FRIDAY = "FRI", "Friday"
        SATURDAY = "SAT", "Saturday"
        SUNDAY = "SUN", "Sunday"

    class Kind(models.TextChoices):
        LEARNING = "learning", "Learning"
        ELEARNING = "elearning", "E-learning"

    name = models.CharField(max_length=120)
    category = models.CharField(max_length=120)
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.LEARNING,
        db_index=True,
    )
    academic_levels = models.ManyToManyField(
        AcademicLevel,
        related_name="learning_schedule_profiles",
    )
    study_days = models.JSONField(default=list)
    lesson_duration_minutes = models.PositiveIntegerField(default=40)
    first_class_start_time = models.TimeField()
    last_class_end_time = models.TimeField("lesson end time")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "category", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "name", "category"],
                name="unique_learning_schedule_profile_per_kind_and_category",
            ),
        ]
        verbose_name = "learning schedule profile"
        verbose_name_plural = "learning schedule profiles"

    def clean(self):
        super().clean()
        valid_days = {choice[0] for choice in self.Weekday.choices}
        if not self.study_days:
            raise ValidationError({"study_days": "Select at least one study day."})
        if any(day not in valid_days for day in self.study_days):
            raise ValidationError({"study_days": "One or more study days are invalid."})
        if self.lesson_duration_minutes <= 0:
            raise ValidationError(
                {"lesson_duration_minutes": "Lesson duration must be greater than zero."}
            )
        if (
            self.first_class_start_time
            and self.last_class_end_time
            and self.last_class_end_time <= self.first_class_start_time
        ):
            raise ValidationError(
                {"last_class_end_time": "Lesson end time must be later than first class start time."}
            )

    def __str__(self):
        return f"{self.category}: {self.name}"


class LearningScheduleActivity(models.Model):
    profile = models.ForeignKey(
        LearningScheduleProfile,
        on_delete=models.CASCADE,
        related_name="activities",
    )
    name = models.CharField(max_length=120)
    start_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["start_time", "order", "name"]
        verbose_name = "learning schedule activity"
        verbose_name_plural = "learning schedule activities"

    @property
    def end_time(self):
        total_minutes = self.start_time.hour * 60 + self.start_time.minute
        total_minutes += self.duration_minutes
        total_minutes %= 24 * 60
        return self.start_time.replace(
            hour=total_minutes // 60,
            minute=total_minutes % 60,
        )

    def __str__(self):
        return f"{self.profile}: {self.name}"


class GradeBand(models.Model):
    academic_level = models.ForeignKey(
        AcademicLevel,
        on_delete=models.CASCADE,
        related_name="grade_bands",
        null=True,
        blank=True,
        verbose_name="academic level",
    )
    code = models.CharField(max_length=20)
    mark_level = models.CharField(max_length=120)
    meaning = models.CharField(max_length=160)
    points = models.PositiveIntegerField(default=0)
    start_percent = models.PositiveIntegerField("start %")
    end_percent = models.PositiveIntegerField("end %")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-end_percent", "-start_percent", "code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_percent__gte=models.F("start_percent")),
                name="grade_band_end_gte_start",
            ),
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(academic_level__isnull=True),
                name="unique_default_grade_band_code",
            ),
            models.UniqueConstraint(
                fields=["academic_level", "code"],
                condition=models.Q(academic_level__isnull=False),
                name="unique_level_grade_band_code",
            ),
        ]
        verbose_name = "grade band"
        verbose_name_plural = "grade bands"

    @property
    def is_default(self):
        return self.academic_level_id is None

    def clean(self):
        super().clean()
        if (
            self.start_percent is not None
            and self.end_percent is not None
            and self.end_percent < self.start_percent
        ):
            raise ValidationError({"end_percent": "End % must be at or above start %."})

    def __str__(self):
        scope = self.academic_level.code if self.academic_level_id else "DEFAULT"
        return f"{scope}: {self.code} ({self.start_percent}-{self.end_percent}%)"


class GeneratedLearningTimetable(models.Model):
    created_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_learning_timetables",
    )
    academic_levels = models.ManyToManyField(
        AcademicLevel,
        related_name="generated_learning_timetables",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "generated learning timetable"
        verbose_name_plural = "generated learning timetables"

    def __str__(self):
        return f"Learning timetable {self.created_at:%Y-%m-%d %H:%M}"


class GeneratedLearningLesson(models.Model):
    generation = models.ForeignKey(
        GeneratedLearningTimetable,
        on_delete=models.CASCADE,
        related_name="lessons",
    )
    academic_level = models.ForeignKey(
        AcademicLevel,
        on_delete=models.CASCADE,
        related_name="generated_lessons",
    )
    academic_class = models.ForeignKey(
        AcademicClass,
        on_delete=models.CASCADE,
        related_name="generated_lessons",
    )
    learning_area = models.ForeignKey(
        LearningArea,
        on_delete=models.CASCADE,
        related_name="generated_lessons",
    )
    teacher = models.ForeignKey(
        "employees.Employee",
        on_delete=models.CASCADE,
        related_name="generated_lessons",
    )
    weekday = models.CharField(max_length=3)
    period_name = models.CharField(max_length=120)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["academic_level__order", "academic_class__order", "weekday", "start_time"]
        verbose_name = "generated learning lesson"
        verbose_name_plural = "generated learning lessons"

    def __str__(self):
        return f"{self.academic_class}: {self.weekday} {self.period_name} {self.learning_area.code}"


class GeneratedELearningTimetable(models.Model):
    created_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_elearning_timetables",
    )
    academic_levels = models.ManyToManyField(
        AcademicLevel,
        related_name="generated_elearning_timetables",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "generated e-learning timetable"
        verbose_name_plural = "generated e-learning timetables"

    def __str__(self):
        return f"E-learning timetable {self.created_at:%Y-%m-%d %H:%M}"


class GeneratedELearningLesson(models.Model):
    generation = models.ForeignKey(
        GeneratedELearningTimetable,
        on_delete=models.CASCADE,
        related_name="lessons",
    )
    academic_level = models.ForeignKey(
        AcademicLevel,
        on_delete=models.CASCADE,
        related_name="generated_elearning_lessons",
    )
    learning_area = models.ForeignKey(
        LearningArea,
        on_delete=models.CASCADE,
        related_name="generated_elearning_lessons",
    )
    teacher = models.ForeignKey(
        "employees.Employee",
        on_delete=models.CASCADE,
        related_name="generated_elearning_lessons",
        limit_choices_to={"assigned_roles__role": "TEACHER"},
    )
    weekday = models.CharField(max_length=3)
    period_name = models.CharField(max_length=120)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["academic_level__order", "weekday", "start_time", "period_name"]
        verbose_name = "generated e-learning lesson"
        verbose_name_plural = "generated e-learning lessons"

    def __str__(self):
        return (
            f"{self.academic_level}: {self.weekday} {self.period_name} "
            f"{self.learning_area.code}"
        )


class GeneratedExamTimetable(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        IN_SESSION = "IN_SESSION", "In session"
        MARKING = "MARKING", "Marking"
        ANALYSING = "ANALYSING", "Analysing"
        PUBLISHED = "PUBLISHED", "Published"

    ACTIVE_WORKFLOW_STATUSES = (
        Status.IN_SESSION,
        Status.MARKING,
        Status.ANALYSING,
    )

    name = models.CharField("assessment name", max_length=120, blank=True, default="")
    created_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_exam_timetables",
    )
    academic_levels = models.ManyToManyField(
        AcademicLevel,
        related_name="generated_exam_timetables",
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="generated_exam_timetables",
        null=True,
        blank=True,
    )
    academic_term = models.ForeignKey(
        AcademicTerm,
        on_delete=models.PROTECT,
        related_name="generated_exam_timetables",
        null=True,
        blank=True,
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )
    deadline = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "generated assessment timetable"
        verbose_name_plural = "generated assessment timetables"

    def save(self, *args, **kwargs):
        self.name = (self.name or "").strip().upper()
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        if self.name:
            return self.name
        if self.academic_year_id and self.academic_term_id:
            return f"{self.academic_year} {self.academic_term.name} assessment"
        return f"Assessment timetable {self.created_at:%Y-%m-%d %H:%M}"

    def __str__(self):
        if self.name:
            return self.name
        if self.academic_year_id and self.academic_term_id:
            return f"{self.academic_year} {self.academic_term.name} assessment timetable"
        return f"Assessment timetable {self.created_at:%Y-%m-%d %H:%M}"


class GeneratedExamSitting(models.Model):
    generation = models.ForeignKey(
        GeneratedExamTimetable,
        on_delete=models.CASCADE,
        related_name="sittings",
    )
    academic_level = models.ForeignKey(
        AcademicLevel,
        on_delete=models.CASCADE,
        related_name="generated_exam_sittings",
    )
    academic_class = models.ForeignKey(
        AcademicClass,
        on_delete=models.CASCADE,
        related_name="generated_exam_sittings",
    )
    learning_area = models.ForeignKey(
        LearningArea,
        on_delete=models.CASCADE,
        related_name="generated_exam_sittings",
    )
    supervisor = models.ForeignKey(
        "employees.Employee",
        on_delete=models.CASCADE,
        related_name="generated_exam_sittings",
        null=True,
        blank=True,
    )
    weekday = models.CharField(max_length=3)
    exam_date = models.DateField(null=True, blank=True)
    period_name = models.CharField(max_length=120)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["academic_level__order", "academic_class__order", "exam_date", "weekday", "start_time"]
        verbose_name = "generated assessment sitting"
        verbose_name_plural = "generated assessment sittings"

    def __str__(self):
        return f"{self.academic_class}: {self.weekday} {self.period_name} {self.learning_area.code}"


class ExamMark(models.Model):
    generation = models.ForeignKey(
        GeneratedExamTimetable,
        on_delete=models.CASCADE,
        related_name="marks",
    )
    student = models.ForeignKey(
        "admissions.Student",
        on_delete=models.CASCADE,
        related_name="exam_marks",
    )
    learning_area = models.ForeignKey(
        LearningArea,
        on_delete=models.CASCADE,
        related_name="exam_marks",
        verbose_name="subject",
    )
    marks = models.PositiveIntegerField()
    out_of_marks = models.PositiveIntegerField(
        "out of marks",
        null=True,
        blank=True,
        help_text="Out-of value that applied when this mark was saved. Kept until the mark is edited.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student__last_name", "student__first_name", "learning_area__display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["generation", "student", "learning_area"],
                name="unique_exam_mark_per_student_and_subject",
            ),
        ]
        verbose_name = "assessment mark"
        verbose_name_plural = "assessment marks"

    def __str__(self):
        return f"{self.student}: {self.learning_area.code} {self.marks}"


class ClassSubjectLessonPlan(models.Model):
    allocation = models.OneToOneField(
        ClassSubjectAllocation,
        on_delete=models.CASCADE,
        related_name="lesson_plan",
    )
    strand = models.CharField(max_length=255, blank=True)
    substrand = models.CharField(max_length=255, blank=True)
    lesson_learning_outcomes = models.TextField(blank=True, verbose_name="lesson learning outcomes")
    key_inquiry_questions = models.TextField(blank=True, verbose_name="key inquiry questions")
    core_competencies = models.TextField(blank=True, verbose_name="core competencies")
    values = models.TextField(blank=True)
    pcis = models.TextField(blank=True, verbose_name="PCIs")
    learning_resources = models.TextField(blank=True, verbose_name="learning resources")
    organization_of_learning = models.TextField(blank=True, verbose_name="organization of learning")
    introduction = models.TextField(blank=True)
    lesson_development = models.TextField(blank=True, verbose_name="lesson development")
    updated_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_lesson_plans",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "class subject lesson plan"
        verbose_name_plural = "class subject lesson plans"

    def __str__(self):
        return f"Lesson plan: {self.allocation}"


class ClassSubjectOutcome(models.Model):
    allocation = models.OneToOneField(
        ClassSubjectAllocation,
        on_delete=models.CASCADE,
        related_name="subject_outcome",
    )
    outcome = models.TextField(blank=True, verbose_name="class subject outcome")
    updated_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_subject_outcomes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "class subject outcome"
        verbose_name_plural = "class subject outcomes"

    def __str__(self):
        return f"Outcome: {self.allocation}"


class SubjectAttendanceSession(models.Model):
    allocation = models.ForeignKey(
        ClassSubjectAllocation,
        on_delete=models.CASCADE,
        related_name="attendance_sessions",
    )
    lesson_date = models.DateField()
    notes = models.TextField(blank=True)
    taken_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subject_attendance_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-lesson_date", "-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["allocation", "lesson_date"],
                name="unique_subject_attendance_per_day",
            ),
        ]
        verbose_name = "subject attendance session"
        verbose_name_plural = "subject attendance sessions"

    def __str__(self):
        return f"{self.allocation} · {self.lesson_date}"


class SubjectAttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Present"
        ABSENT = "ABSENT", "Absent"
        LATE = "LATE", "Late"
        EXCUSED = "EXCUSED", "Excused"

    session = models.ForeignKey(
        SubjectAttendanceSession,
        on_delete=models.CASCADE,
        related_name="records",
    )
    student = models.ForeignKey(
        "admissions.Student",
        on_delete=models.CASCADE,
        related_name="subject_attendance_records",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PRESENT,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student__last_name", "student__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "student"],
                name="unique_subject_attendance_per_student",
            ),
        ]
        verbose_name = "subject attendance record"
        verbose_name_plural = "subject attendance records"

    def __str__(self):
        return f"{self.student}: {self.get_status_display()} ({self.session.lesson_date})"


class ELearningSubjectLessonPlan(models.Model):
    allocation = models.OneToOneField(
        ELearningSubjectAllocation,
        on_delete=models.CASCADE,
        related_name="lesson_plan",
    )
    strand = models.CharField(max_length=255, blank=True)
    substrand = models.CharField(max_length=255, blank=True)
    lesson_learning_outcomes = models.TextField(blank=True, verbose_name="lesson learning outcomes")
    key_inquiry_questions = models.TextField(blank=True, verbose_name="key inquiry questions")
    core_competencies = models.TextField(blank=True, verbose_name="core competencies")
    values = models.TextField(blank=True)
    pcis = models.TextField(blank=True, verbose_name="PCIs")
    learning_resources = models.TextField(blank=True, verbose_name="learning resources")
    organization_of_learning = models.TextField(blank=True, verbose_name="organization of learning")
    introduction = models.TextField(blank=True)
    lesson_development = models.TextField(blank=True, verbose_name="lesson development")
    updated_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_elearning_lesson_plans",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "e-learning subject lesson plan"
        verbose_name_plural = "e-learning subject lesson plans"

    def __str__(self):
        return f"E-learning lesson plan: {self.allocation}"


class ELearningSubjectOutcome(models.Model):
    allocation = models.OneToOneField(
        ELearningSubjectAllocation,
        on_delete=models.CASCADE,
        related_name="subject_outcome",
    )
    outcome = models.TextField(blank=True, verbose_name="e-learning subject outcome")
    updated_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_elearning_subject_outcomes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "e-learning subject outcome"
        verbose_name_plural = "e-learning subject outcomes"

    def __str__(self):
        return f"E-learning outcome: {self.allocation}"


class ELearningAttendanceSession(models.Model):
    allocation = models.ForeignKey(
        ELearningSubjectAllocation,
        on_delete=models.CASCADE,
        related_name="attendance_sessions",
    )
    lesson_date = models.DateField()
    notes = models.TextField(blank=True)
    taken_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="elearning_attendance_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-lesson_date", "-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["allocation", "lesson_date"],
                name="unique_elearning_attendance_per_day",
            ),
        ]
        verbose_name = "e-learning attendance session"
        verbose_name_plural = "e-learning attendance sessions"

    def __str__(self):
        return f"{self.allocation} · {self.lesson_date}"


class ELearningAttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Present"
        ABSENT = "ABSENT", "Absent"
        LATE = "LATE", "Late"
        EXCUSED = "EXCUSED", "Excused"

    session = models.ForeignKey(
        ELearningAttendanceSession,
        on_delete=models.CASCADE,
        related_name="records",
    )
    student = models.ForeignKey(
        "admissions.Student",
        on_delete=models.CASCADE,
        related_name="elearning_attendance_records",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PRESENT,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student__last_name", "student__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "student"],
                name="unique_elearning_attendance_per_student",
            ),
        ]
        verbose_name = "e-learning attendance record"
        verbose_name_plural = "e-learning attendance records"

    def __str__(self):
        return f"{self.student}: {self.get_status_display()} ({self.session.lesson_date})"


class ELearningLearningMaterial(models.Model):
    """Portal-ready learning materials for an e-learning subject allocation."""

    class ContentFormat(models.TextChoices):
        NOTES = "NOTES", "Notes/handouts (PDF)"
        LECTURE_VIDEO = "LECTURE_VIDEO", "Lecture video (MP4)"
        SLIDES = "SLIDES", "Slides (PDF or PPTX)"
        QUIZ_SCORM = "QUIZ_SCORM", "Quizzes/interactive (SCORM package)"
        AUDIO = "AUDIO", "Audio (MP3)"

    FORMAT_EXTENSIONS = {
        ContentFormat.NOTES: (".pdf",),
        ContentFormat.LECTURE_VIDEO: (".mp4",),
        ContentFormat.SLIDES: (".pdf", ".pptx"),
        ContentFormat.QUIZ_SCORM: (".zip",),
        ContentFormat.AUDIO: (".mp3",),
    }

    FORMAT_MIME_TYPES = {
        ContentFormat.NOTES: ("application/pdf",),
        ContentFormat.LECTURE_VIDEO: ("video/mp4",),
        ContentFormat.SLIDES: (
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        ContentFormat.QUIZ_SCORM: ("application/zip", "application/x-zip-compressed"),
        ContentFormat.AUDIO: ("audio/mpeg", "audio/mp3"),
    }

    allocation = models.ForeignKey(
        ELearningSubjectAllocation,
        on_delete=models.CASCADE,
        related_name="learning_materials",
        verbose_name="e-learning subject",
    )
    content_format = models.CharField(
        max_length=20,
        choices=ContentFormat.choices,
        verbose_name="material format",
    )
    category = models.CharField(max_length=120, verbose_name="category")
    name = models.CharField(max_length=200, verbose_name="material name")
    description = models.TextField(blank=True, verbose_name="description")
    cover_image = models.ImageField(
        upload_to="elearning/materials/covers/%Y/%m/",
        blank=True,
        verbose_name="cover image",
    )
    material_file = models.FileField(
        upload_to="elearning/materials/files/%Y/%m/",
        verbose_name="material file",
    )
    original_filename = models.CharField(max_length=255, blank=True)
    file_extension = models.CharField(max_length=12, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=120, blank=True)
    is_published = models.BooleanField(
        default=True,
        help_text="Published materials appear for download in student and parent portals.",
    )
    uploaded_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_elearning_materials",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "name"]
        verbose_name = "e-learning learning material"
        verbose_name_plural = "e-learning learning materials"

    def __str__(self):
        return f"{self.name} ({self.get_content_format_display()})"

    @property
    def allowed_extensions(self):
        return self.FORMAT_EXTENSIONS.get(self.content_format, ())

    @property
    def download_filename(self):
        base = re.sub(r"[^\w\s.-]", "", self.name or "material").strip() or "material"
        base = re.sub(r"\s+", "-", base)[:80]
        ext = self.file_extension or ""
        if not ext.startswith(".") and ext:
            ext = f".{ext}"
        if not ext and self.original_filename:
            from pathlib import Path

            ext = Path(self.original_filename).suffix.lower()
        return f"{base}{ext}"

    @property
    def human_file_size(self):
        size = self.file_size or 0
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    def sync_file_metadata(self):
        uploaded = self.material_file
        if not uploaded:
            return
        name = getattr(uploaded, "name", "") or ""
        from pathlib import Path

        path_name = Path(name).name
        self.original_filename = path_name
        self.file_extension = Path(path_name).suffix.lower()
        try:
            self.file_size = uploaded.size or 0
        except (OSError, ValueError):
            self.file_size = self.file_size or 0
        content_type = getattr(uploaded, "content_type", "") or ""
        if not content_type:
            import mimetypes

            guessed, _encoding = mimetypes.guess_type(path_name)
            content_type = guessed or "application/octet-stream"
        self.content_type = content_type[:120]

    def open_download_response(self, as_attachment=True):
        from django.http import FileResponse, Http404

        if not self.material_file:
            raise Http404("Material file not found.")
        try:
            handle = self.material_file.open("rb")
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise Http404("Material file not found.") from exc
        content_type = self.content_type or "application/octet-stream"
        response = FileResponse(
            handle,
            as_attachment=as_attachment,
            filename=self.download_filename,
        )
        response["Content-Type"] = content_type
        if self.file_size:
            response["Content-Length"] = str(self.file_size)
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, max-age=300"
        if not as_attachment:
            # Prefer browser preview for PDF / video / audio.
            response["Content-Disposition"] = f'inline; filename="{self.download_filename}"'
        return response

    def open_view_response(self):
        return self.open_download_response(as_attachment=False)


class ELearningAssessment(models.Model):
    name = models.CharField(max_length=120)
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
        related_name="elearning_assessments",
    )
    academic_term = models.ForeignKey(
        AcademicTerm,
        on_delete=models.CASCADE,
        related_name="elearning_assessments",
    )
    created_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_elearning_assessments",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "name"]
        verbose_name = "e-learning assessment"
        verbose_name_plural = "e-learning assessments"

    def __str__(self):
        return f"{self.name} ({self.academic_term})"

    @property
    def display_name(self):
        return (self.name or "").strip() or f"{self.academic_term.name} e-learning assessment"


class ELearningAssessmentMark(models.Model):
    assessment = models.ForeignKey(
        ELearningAssessment,
        on_delete=models.CASCADE,
        related_name="marks",
    )
    student = models.ForeignKey(
        "admissions.Student",
        on_delete=models.CASCADE,
        related_name="elearning_assessment_marks",
    )
    learning_area = models.ForeignKey(
        LearningArea,
        on_delete=models.CASCADE,
        related_name="elearning_assessment_marks",
        verbose_name="subject",
    )
    marks = models.PositiveIntegerField()
    out_of_marks = models.PositiveIntegerField(
        "out of marks",
        null=True,
        blank=True,
        help_text="Out-of value that applied when this mark was saved. Kept until the mark is edited.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student__last_name", "student__first_name", "learning_area__display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "student", "learning_area"],
                name="unique_elearning_mark_per_student_and_subject",
            ),
        ]
        verbose_name = "e-learning assessment mark"
        verbose_name_plural = "e-learning assessment marks"

    def __str__(self):
        return f"{self.student}: {self.learning_area.code} {self.marks}"


class ClassAttendanceSession(models.Model):
    academic_class = models.ForeignKey(
        AcademicClass,
        on_delete=models.CASCADE,
        related_name="class_attendance_sessions",
        verbose_name="class",
    )
    attendance_date = models.DateField()
    notes = models.TextField(blank=True)
    taken_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="class_attendance_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-attendance_date", "-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_class", "attendance_date"],
                name="unique_class_attendance_per_day",
            ),
        ]
        verbose_name = "class attendance session"
        verbose_name_plural = "class attendance sessions"

    def __str__(self):
        return f"{self.academic_class}: {self.attendance_date}"


class ClassAttendanceRecord(models.Model):
    session = models.ForeignKey(
        ClassAttendanceSession,
        on_delete=models.CASCADE,
        related_name="records",
    )
    student = models.ForeignKey(
        "admissions.Student",
        on_delete=models.CASCADE,
        related_name="class_attendance_records",
    )
    morning = models.BooleanField("morning session", default=False)
    afternoon = models.BooleanField("afternoon session", default=False)
    evening = models.BooleanField("evening session", default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student__last_name", "student__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "student"],
                name="unique_class_attendance_per_student",
            ),
        ]
        verbose_name = "class attendance record"
        verbose_name_plural = "class attendance records"

    def __str__(self):
        flags = []
        if self.morning:
            flags.append("AM")
        if self.afternoon:
            flags.append("PM")
        if self.evening:
            flags.append("EVE")
        return f"{self.student}: {', '.join(flags) or 'none'} ({self.session.attendance_date})"
