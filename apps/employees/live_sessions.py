"""Track and identify users with live portal/workspace sessions."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

LIVE_SESSION_ACTIVITY_KEY = "edu_last_activity"
LIVE_SESSION_WINDOW = timedelta(minutes=15)


def touch_live_session(session, request):
    if session is None or not hasattr(session, "__setitem__"):
        return False

    is_live = False
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        is_live = True
    if session.get("student_id") or session.get("parent_id"):
        is_live = True

    if not is_live:
        return False

    session[LIVE_SESSION_ACTIVITY_KEY] = timezone.now().isoformat()
    session.modified = True
    return True


def parse_activity_at(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed
    except (TypeError, ValueError):
        return None


def activity_from_expire_date(expire_date):
    if not expire_date:
        return None
    cookie_age = getattr(settings, "SESSION_COOKIE_AGE", 1209600)
    return expire_date - timedelta(seconds=cookie_age)


def session_last_activity(data, expire_date=None):
    tracked = parse_activity_at(data.get(LIVE_SESSION_ACTIVITY_KEY))
    if tracked is not None:
        return tracked
    return activity_from_expire_date(expire_date)


def is_live_session(data, expire_date=None):
    last_activity = session_last_activity(data, expire_date)
    if last_activity is None:
        return False
    return timezone.now() - last_activity <= LIVE_SESSION_WINDOW


def format_last_seen(last_activity):
    if last_activity is None:
        return "Unknown"
    delta = timezone.now() - last_activity
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "Just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours} hr ago"
