"""
cPanel may auto-manage this file. Prefer django_wsgi.py as the startup file.

If you keep this file as the real entrypoint, it must define `application`
directly and must NOT call load_source(..., 'passenger_wsgi.py').
"""

import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

from config.startup import apply_pending_migrations

apply_pending_migrations()
