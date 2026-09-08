"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve


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
    path('admin/', admin.site.urls),
    path('', include('apps.employees.urls')),
    path('', include('apps.admissions.urls')),
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
