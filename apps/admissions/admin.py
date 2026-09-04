from django.contrib import admin
from django import forms

from .models import AdmissionSettings, ParentGuardian, Student


@admin.register(AdmissionSettings)
class AdmissionSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "admissions_enabled",
        "auto_generate_admission_number",
        "admission_number_prefix",
        "admission_number_next",
        "admission_number_pad_width",
    )
    fields = (
        "admissions_enabled",
        "auto_generate_admission_number",
        "admission_number_prefix",
        "admission_number_next",
        "admission_number_pad_width",
    )

    def has_add_permission(self, request):
        return not AdmissionSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class PortalAccountAdminForm(forms.ModelForm):
    new_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput,
        help_text="Set a portal password when activating the account (letters and/or digits).",
    )

    def save(self, commit=True):
        instance = super().save(commit=False)
        password = self.cleaned_data.get("new_password")
        if password:
            instance.set_password(password)
        if commit:
            instance.save()
        return instance


@admin.register(ParentGuardian)
class ParentGuardianAdmin(admin.ModelAdmin):
    form = PortalAccountAdminForm
    list_display = ("full_name", "phone_number", "email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("full_name", "phone_number", "email")
    readonly_fields = ("password", "created_at")
    fields = (
        "full_name",
        "relationship_to_student",
        "phone_number",
        "email",
        "is_active",
        "new_password",
        "password",
        "created_at",
    )


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    form = PortalAccountAdminForm
    list_display = (
        "admission_number",
        "assessment_number",
        "first_name",
        "middle_name",
        "last_name",
        "class_group",
        "academic_level",
        "parent_guardian",
        "enrollment_status",
        "is_active",
        "is_suspended",
    )
    list_filter = (
        "academic_level",
        "gender",
        "sponsorship_category",
        "enrollment_status",
        "is_active",
        "is_suspended",
    )
    search_fields = (
        "admission_number",
        "assessment_number",
        "first_name",
        "middle_name",
        "last_name",
        "parent_guardian__full_name",
    )
    readonly_fields = ("password", "admitted_at", "cleared_at")
    fields = (
        "first_name",
        "middle_name",
        "last_name",
        "date_of_birth",
        "gender",
        "academic_level",
        "admission_number",
        "class_group",
        "assessment_number",
        "previous_school",
        "sponsorship_category",
        "sponsor_details",
        "parent_guardian",
        "home_address",
        "medical_notes",
        "special_needs",
        "emergency_contact",
        "enrollment_status",
        "clearance_reason",
        "cleared_at",
        "is_active",
        "is_suspended",
        "new_password",
        "password",
        "admitted_at",
    )
