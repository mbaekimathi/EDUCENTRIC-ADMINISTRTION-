from django.urls import path

from . import views

app_name = "admissions"

urlpatterns = [
    path("admissions/new/", views.admit_student, name="admit_student"),
    path("portal/", views.portal_login, name="portal_login"),
    path("portal/student/", views.student_portal, name="student_portal"),
    path(
        "portal/student/materials/<int:material_id>/view/",
        views.student_portal_material_view,
        name="student_portal_material_view",
    ),
    path(
        "portal/student/materials/<int:material_id>/download/",
        views.student_portal_material_download,
        name="student_portal_material_download",
    ),
    path("portal/parent/", views.parent_portal, name="parent_portal"),
    path(
        "portal/parent/materials/<int:material_id>/view/",
        views.parent_portal_material_view,
        name="parent_portal_material_view",
    ),
    path(
        "portal/parent/materials/<int:material_id>/download/",
        views.parent_portal_material_download,
        name="parent_portal_material_download",
    ),
    path("portal/logout/", views.portal_logout, name="portal_logout"),
]
