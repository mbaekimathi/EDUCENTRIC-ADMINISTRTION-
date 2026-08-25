from django.contrib import admin

from .models import (
    AcademicClass,
    AcademicLevel,
    AcademicTerm,
    AcademicYear,
    ClassSubjectAllocation,
    CombinedExamSubject,
    CombinedExamSubjectComponent,
    ELearningLearningMaterial,
    ELearningSubjectAllocation,
    ExamMark,
    ExamSubjectSetting,
    ExamSupervisorAllocation,
    GeneratedExamSitting,
    GeneratedExamTimetable,
    GeneratedELearningLesson,
    GeneratedELearningTimetable,
    GeneratedLearningLesson,
    GeneratedLearningTimetable,
    GradeBand,
    LearningArea,
)


@admin.register(AcademicLevel)
class AcademicLevelAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "order", "status", "updated_at")
    list_filter = ("status", "category")
    search_fields = ("name", "code", "description")
    ordering = ("order", "name")


@admin.register(AcademicClass)
class AcademicClassAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "academic_level", "order", "status", "updated_at")
    list_filter = ("status", "academic_level")
    search_fields = ("name", "code", "academic_level__name", "academic_level__code")
    ordering = ("academic_level__order", "order", "name")


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "is_current", "status", "updated_at")
    list_filter = ("status", "is_current")
    search_fields = ("name",)
    ordering = ("-start_date", "name")


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "academic_year",
        "start_date",
        "end_date",
        "opening_date",
        "midterm_date",
        "closing_date",
        "order",
        "is_current",
    )
    list_filter = ("academic_year", "is_current")
    search_fields = ("name", "academic_year__name")
    ordering = ("academic_year", "order", "start_date")


@admin.register(LearningArea)
class LearningAreaAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "display_order", "status", "updated_at")
    list_filter = ("status", "academic_levels")
    search_fields = ("name", "code", "description")
    filter_horizontal = ("academic_levels",)
    ordering = ("display_order", "name")


@admin.register(ClassSubjectAllocation)
class ClassSubjectAllocationAdmin(admin.ModelAdmin):
    list_display = ("academic_class", "learning_area", "teacher", "updated_at")
    list_filter = ("academic_class__academic_level", "learning_area")
    search_fields = (
        "academic_class__name",
        "learning_area__name",

        "learning_area__code",
        "teacher__first_name",
        "teacher__last_name",
        "teacher__employee_code",
    )


@admin.register(ELearningSubjectAllocation)
class ELearningSubjectAllocationAdmin(admin.ModelAdmin):
    list_display = ("academic_level", "learning_area", "teacher", "updated_at")
    list_filter = ("academic_level", "learning_area")
    search_fields = (
        "academic_level__name",
        "learning_area__name",
        "learning_area__code",
        "teacher__first_name",
        "teacher__last_name",
        "teacher__employee_code",
    )


@admin.register(ELearningLearningMaterial)
class ELearningLearningMaterialAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "content_format",
        "category",
        "allocation",
        "is_published",
        "file_size",
        "updated_at",
    )
    list_filter = ("content_format", "is_published", "allocation__academic_level")
    search_fields = ("name", "category", "description", "original_filename")


@admin.register(GeneratedLearningTimetable)
class GeneratedLearningTimetableAdmin(admin.ModelAdmin):
    list_display = ("id", "created_by", "created_at")
    list_filter = ("created_at",)
    filter_horizontal = ("academic_levels",)


@admin.register(GeneratedLearningLesson)
class GeneratedLearningLessonAdmin(admin.ModelAdmin):
    list_display = (
        "academic_class",
        "weekday",
        "period_name",
        "learning_area",
        "teacher",
        "generation",
    )
    list_filter = ("weekday", "academic_level")
    search_fields = (
        "academic_class__name",
        "learning_area__name",
        "teacher__first_name",
        "teacher__last_name",
    )


@admin.register(GeneratedELearningTimetable)
class GeneratedELearningTimetableAdmin(admin.ModelAdmin):
    list_display = ("id", "created_by", "created_at")
    list_filter = ("created_at",)
    filter_horizontal = ("academic_levels",)


@admin.register(GeneratedELearningLesson)
class GeneratedELearningLessonAdmin(admin.ModelAdmin):
    list_display = (
        "academic_level",
        "weekday",
        "period_name",
        "learning_area",
        "teacher",
        "generation",
    )
    list_filter = ("weekday", "academic_level")
    search_fields = (
        "academic_level__name",
        "learning_area__name",
        "teacher__first_name",
        "teacher__last_name",
    )


@admin.register(ExamSupervisorAllocation)
class ExamSupervisorAllocationAdmin(admin.ModelAdmin):
    list_display = ("academic_class", "learning_area", "supervisor", "updated_at")
    list_filter = ("academic_class__academic_level", "learning_area")
    search_fields = (
        "academic_class__name",
        "learning_area__name",
        "learning_area__code",
        "supervisor__first_name",
        "supervisor__last_name",
        "supervisor__employee_code",
    )


@admin.register(GeneratedExamTimetable)
class GeneratedExamTimetableAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "academic_year", "academic_term", "start_date", "end_date", "created_by", "created_at")
    list_filter = ("academic_year", "academic_term", "created_at")
    search_fields = ("name",)
    filter_horizontal = ("academic_levels",)


@admin.register(GeneratedExamSitting)
class GeneratedExamSittingAdmin(admin.ModelAdmin):
    list_display = (
        "academic_class",
        "exam_date",
        "weekday",
        "period_name",
        "learning_area",
        "supervisor",
        "generation",
    )
    list_filter = ("exam_date", "weekday", "academic_level")
    search_fields = (
        "academic_class__name",
        "learning_area__name",
        "supervisor__first_name",
        "supervisor__last_name",
    )


@admin.register(ExamMark)
class ExamMarkAdmin(admin.ModelAdmin):
    list_display = ("student", "learning_area", "marks", "generation", "updated_at")
    list_filter = ("generation", "learning_area")
    search_fields = (
        "student__first_name",
        "student__last_name",
        "student__admission_number",
        "learning_area__code",
    )


@admin.register(ExamSubjectSetting)
class ExamSubjectSettingAdmin(admin.ModelAdmin):
    list_display = ("academic_level", "learning_area", "out_of_marks", "updated_at")
    list_filter = ("academic_level",)
    search_fields = ("academic_level__name", "learning_area__name", "learning_area__code")


class CombinedExamSubjectComponentInline(admin.TabularInline):
    model = CombinedExamSubjectComponent
    extra = 0


@admin.register(CombinedExamSubject)
class CombinedExamSubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "academic_level", "updated_at")
    list_filter = ("academic_level",)
    search_fields = ("name", "code", "academic_level__name")
    inlines = [CombinedExamSubjectComponentInline]


@admin.register(GradeBand)
class GradeBandAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "academic_level",
        "mark_level",
        "meaning",
        "points",
        "start_percent",
        "end_percent",
    )
    list_filter = ("academic_level",)
    search_fields = ("code", "mark_level", "meaning", "academic_level__name")
    ordering = ("academic_level__order", "-end_percent", "-start_percent", "code")
