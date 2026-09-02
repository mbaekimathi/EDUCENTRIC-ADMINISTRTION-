from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.forms import ModelForm, Select

from .models import Employee, EmployeeRole


class EmployeeAdminForm(ModelForm):
    class Meta:
        model = Employee
        fields = "__all__"
        labels = {
            "employee_code": "Employment number",
            "employment_number": "Employee code",
        }


class EmployeeRoleInline(admin.TabularInline):
    model = EmployeeRole
    extra = 0


@admin.register(Employee)
class EmployeeAdmin(UserAdmin):
    model = Employee
    form = EmployeeAdminForm
    list_display = (
        "employee_code",
        "employment_number",
        "first_name",
        "last_name",
        "email",
        "role",
        "approval_status",
        "is_suspended",
        "is_active",
    )
    list_editable = ("role", "approval_status")
    list_filter = ("approval_status", "role", "is_suspended", "is_active", "is_staff", "title")
    ordering = ("employee_code",)
    search_fields = ("employee_code", "employment_number", "first_name", "last_name", "email")
    actions = ("approve_selected_employees", "reject_selected_employees")
    inlines = (EmployeeRoleInline,)
    fieldsets = (
        (None, {"fields": ("employee_code", "employment_number", "password")}),
        (
            "Personal information",
            {
                "fields": (
                    "title",
                    "first_name",
                    "last_name",
                    "email",
                    "phone_number",
                    "profile_image",
                )
            },
        ),
        (
            "Role and approval",
            {
                "fields": ("role", "approval_status", "is_suspended"),
                "description": (
                    "Primary role is the default workspace. Add extra roles in the "
                    "Employee roles section below."
                ),
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "employee_code",
                    "employment_number",
                    "email",
                    "title",
                    "first_name",
                    "last_name",
                    "role",
                    "approval_status",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in {"role", "approval_status"}:
            kwargs["widget"] = Select
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if obj.approval_status == Employee.ApprovalStatus.APPROVED and not obj.is_suspended:
            obj.is_active = True
        else:
            obj.is_active = False
        super().save_model(request, obj, form, change)

    @admin.action(description="Approve selected employees and activate login")
    def approve_selected_employees(self, request, queryset):
        queryset.update(
            approval_status=Employee.ApprovalStatus.APPROVED,
            is_suspended=False,
            is_active=True,
        )

    @admin.action(description="Reject selected employees and deactivate login")
    def reject_selected_employees(self, request, queryset):
        queryset.update(
            approval_status=Employee.ApprovalStatus.REJECTED,
            is_active=False,
        )
