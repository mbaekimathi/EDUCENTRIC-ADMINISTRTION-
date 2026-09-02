from django.apps import AppConfig


class EmployeesConfig(AppConfig):
    name = 'apps.employees'

    def ready(self):
        from . import signals  # noqa: F401
