import inspect

from django.db import models


def check_constraint(*, name, condition, **kwargs):
    """Build CheckConstraint across Django 5.0 (`check=`) and 5.1+ (`condition=`)."""
    params = inspect.signature(models.CheckConstraint.__init__).parameters
    if "condition" in params:
        return models.CheckConstraint(condition=condition, name=name, **kwargs)
    return models.CheckConstraint(check=condition, name=name, **kwargs)
