from django.shortcuts import redirect
from django.urls import reverse

from .live_sessions import touch_live_session
from .workspace import needs_login_role_selection


class RequireWorkspaceRoleSelectionMiddleware:
    """Send multi-role users to role selection until they pick an active workspace."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_redirect(request):
            return redirect("employees:select_login_role")
        return self.get_response(request)

    def _should_redirect(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        path = request.path or ""
        if not needs_login_role_selection(request):
            return False
        exempt_prefixes = (
            reverse("employees:select_login_role"),
            reverse("employees:logout"),
            reverse("employees:login"),
            "/admin/",
            "/static/",
            "/media/",
        )
        return not any(path == prefix or path.startswith(prefix) for prefix in exempt_prefixes)


class TrackLiveSessionActivityMiddleware:
    """Stamp sessions when authenticated users are actively using the system."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        touch_live_session(getattr(request, "session", None), request)
        return self.get_response(request)
