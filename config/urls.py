"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
"""
from django.contrib import admin
from django.conf import settings
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.decorators.cache import cache_control
from django.views.static import serve


@cache_control(public=True, max_age=86400)
def service_worker_stub(request):
    """Browsers may request /sw.js; return a tiny no-op instead of a heavy 404 page."""
    return HttpResponse(
        "// Educentric: no service worker registered.\n",
        content_type="application/javascript; charset=utf-8",
        status=200,
    )


def _media_serve(request, path):
    """Serve uploads with browser caching so logos are not re-downloaded every visit."""
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    if path.startswith("school/branding/"):
        # Optimized logos use a new filename on replace, so long cache is safe.
        response["Cache-Control"] = "public, max-age=2592000, immutable"
    else:
        response["Cache-Control"] = "public, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    return response


urlpatterns = [
    path("sw.js", service_worker_stub, name="service_worker_stub"),
    path("admin/", admin.site.urls),
    path("", include("apps.employees.urls")),
    path("", include("apps.admissions.urls")),
]

# django.conf.urls.static.static() is a no-op when DEBUG=False, so logos
# uploaded on hosted (DEBUG=False) never get a /media/ route. Always register
# an explicit media route when DEBUG or SERVE_MEDIA is enabled.
if settings.DEBUG or getattr(settings, "SERVE_MEDIA", False):
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            _media_serve,
        ),
    ]
