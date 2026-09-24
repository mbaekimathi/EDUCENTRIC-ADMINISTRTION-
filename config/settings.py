"""
Django settings for the Educentric ADMINISTRATION system.

Works on cPanel (Passenger) and later on a VPS (Gunicorn + Nginx).
"""

import os
import sys
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

from config.db import build_mysql_database

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(
    DEBUG=(bool, True),
    LOCAL=(bool, True),
)
environ.Env.read_env(BASE_DIR / ".env")

_LOCAL_DEV_HOSTS = {"localhost", "127.0.0.1", "testserver"}


def _env_key_set(key: str) -> bool:
    return bool(os.environ.get(key, "").strip())


def _infer_is_local() -> bool:
    legacy_hosts = env.list("ALLOWED_HOSTS", default=[])
    if legacy_hosts and not set(legacy_hosts) <= _LOCAL_DEV_HOSTS:
        return False
    if _env_key_set("HOSTED_DB_NAME") or _env_key_set("HOSTED_ALLOWED_HOSTS"):
        return False
    return True


_IS_LOCAL = env.bool("LOCAL") if "LOCAL" in os.environ else _infer_is_local()
_ENV_PROFILE = "LOCAL_" if _IS_LOCAL else "HOSTED_"


def _env_str(name: str, default=""):
    prefixed = f"{_ENV_PROFILE}{name}"
    if _env_key_set(prefixed):
        return env(prefixed, default=default)
    if _env_key_set(name):
        return env(name, default=default)
    return default


def _env_bool(name: str, default=False):
    prefixed = f"{_ENV_PROFILE}{name}"
    if prefixed in os.environ:
        return env.bool(prefixed, default=default)
    if name in os.environ:
        return env.bool(name, default=default)
    return default


def _env_list(name: str, *, local_default=None):
    prefixed = f"{_ENV_PROFILE}{name}"
    if _env_key_set(prefixed):
        return env.list(prefixed)
    if _env_key_set(name):
        return env.list(name)
    if _IS_LOCAL and local_default is not None:
        return list(local_default)
    return []


def _merge_unique(*groups):
    seen = []
    for group in groups:
        for item in group:
            if item not in seen:
                seen.append(item)
    return seen


DEBUG = _env_bool("DEBUG", default=_IS_LOCAL)
SECRET_KEY = env("SECRET_KEY", default="")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "unsafe-development-key-change-before-production"
    else:
        raise ImproperlyConfigured("Set SECRET_KEY in .env when DEBUG=False")

ALLOWED_HOSTS = _merge_unique(
    _env_list("ALLOWED_HOSTS", local_default=["localhost", "127.0.0.1", "testserver"]),
    env.list("HOSTED_ALLOWED_HOSTS", default=[]),
)
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "Set HOSTED_ALLOWED_HOSTS (or ALLOWED_HOSTS) in .env when deploying to production."
    )

CSRF_TRUSTED_ORIGINS = _merge_unique(
    _env_list("CSRF_TRUSTED_ORIGINS", local_default=[]),
    env.list("HOSTED_CSRF_TRUSTED_ORIGINS", default=[]),
    env.list("CSRF_TRUSTED_ORIGINS", default=[]),
)

# cPanel / Cloudflare / Nginx terminate SSL in front of the app.
if _env_bool("USE_PROXY_SSL_HEADER", default=not DEBUG):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'apps.employees',
    'apps.admissions',
    'apps.curriculum.apps.CurriculumConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.employees.middleware.TrackLiveSessionActivityMiddleware',
    'apps.employees.middleware.RequireWorkspaceRoleSelectionMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.employees.context_processors.school_branding',
                'apps.employees.context_processors.workspace',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

# Prefer MySQL when DB_NAME is set (see .env.example). Empty DB_PASSWORD is valid for local root.
# On cPanel, "localhost" often needs a Unix socket (PyMySQL otherwise uses TCP → Errno 111).
_db_name = _env_str("DB_NAME", default="").strip()
if _db_name:
    # cPanel/Passenger recycles workers; persistent DB sockets often become
    # "MySQL server has gone away". Default CONN_MAX_AGE=0 (set DB_CONN_MAX_AGE to override).
    DATABASES = {
        "default": build_mysql_database(
            name=_db_name,
            user=_env_str("DB_USER", default="root"),
            password=_env_str("DB_PASSWORD", default=""),
            host=_env_str("DB_HOST", default="127.0.0.1"),
            port=env("DB_PORT", default="3306"),
            conn_max_age=env.int("DB_CONN_MAX_AGE", default=0),
            socket=env("DB_SOCKET", default=""),
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Passwords may include letters, digits, or both (minimum 6 characters).
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 6},
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# Prefer compressed files when collectstatic has run; fall back cleanly on cPanel.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_MANIFEST_STRICT = False
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
# Serve uploaded media from Django by default (cPanel / shared hosting has no media alias).
# On a VPS with Nginx media mapping, set SERVE_MEDIA=False in .env.
SERVE_MEDIA = _env_bool("SERVE_MEDIA", default=True)

_auto_migrate = _env_bool("AUTO_MIGRATE", default=_IS_LOCAL)
os.environ["AUTO_MIGRATE"] = "true" if _auto_migrate else "false"

AUTH_USER_MODEL = "employees.Employee"
LOGIN_URL = "employees:login"
LOGIN_REDIRECT_URL = "employees:dashboard"
LOGOUT_REDIRECT_URL = "employees:login"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis is preferred in production; the local cache keeps development friction-free.
if env("REDIS_URL", default=""):
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": env("REDIS_URL"),
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            "TIMEOUT": 300,
            "KEY_PREFIX": "edu_admin",
        }
    }
    SESSION_ENGINE = "django.contrib.sessions.backends.cache"
    SESSION_CACHE_ALIAS = "default"
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "edu-admin-development-cache",
            "TIMEOUT": 300,
        }
    }

SESSION_COOKIE_NAME = "edu_admin_sessionid"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", default=not DEBUG)
# runserver is HTTP-only; never redirect browsers to https:// on the dev port.
if "runserver" in sys.argv:
    SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG


