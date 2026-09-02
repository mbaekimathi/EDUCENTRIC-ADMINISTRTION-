"""System health and operational analytics for the IT Support workspace."""

from __future__ import annotations

import platform
import shutil
import time
from datetime import timedelta
from pathlib import Path

import django
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Count
from django.utils import timezone

COUNTS_CACHE_KEY = "system_perf:counts"
COUNTS_CACHE_TTL = 60
DB_INFO_CACHE_KEY = "system_perf:db_info"
DB_INFO_CACHE_TTL = 300
TABLES_CACHE_KEY = "system_perf:tables"
TABLES_CACHE_TTL = 120
MEDIA_CACHE_KEY = "system_perf:media"
MEDIA_CACHE_TTL = 300
OPERATIONS_CACHE_KEY = "system_perf:operations"
OPERATIONS_CACHE_TTL = 60
LATENCY_HISTORY_KEY = "system_perf:latency_history"
LATENCY_HISTORY_MAX = 24
PROBE_CACHE_KEY = "system_perf:probe"
ACTIVE_SESSIONS_CACHE_KEY = "system_perf:active_sessions"
ACTIVE_SESSIONS_CACHE_TTL = 10
STRESS_EVENTS_KEY = "system_perf:stress_events"
STRESS_EVENTS_MAX = 20
STRESS_EVENTS_TTL = 604800
STRESS_RECORD_COOLDOWN_KEY = "system_perf:stress_last_record"
STRESS_RECORD_COOLDOWN_SEC = 60
STRESS_SESSION_SAMPLE = 20
MAX_SESSION_USERS_LISTED = 50


def _iter_database_session_data():
    from django.contrib.sessions.models import Session

    now = timezone.now()
    for row in Session.objects.filter(expire_date__gte=now).iterator(chunk_size=200):
        try:
            yield row.get_decoded(), row.expire_date
        except Exception:
            continue


def _iter_cache_backed_session_data():
    from django.contrib.sessions.backends.cache import SessionStore

    try:
        from django_redis import get_redis_connection
    except ImportError:
        return

    cache_alias = getattr(settings, "SESSION_CACHE_ALIAS", "default")
    try:
        conn = get_redis_connection(cache_alias)
    except Exception:
        return

    key_prefix = settings.CACHES.get(cache_alias, {}).get("KEY_PREFIX", "")
    prefix_token = SessionStore.cache_key_prefix
    pattern = f"{key_prefix}:*:{prefix_token}*" if key_prefix else f"*{prefix_token}*"

    for raw_key in conn.scan_iter(match=pattern, count=200):
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        if prefix_token not in key:
            continue
        session_key = key.rsplit(prefix_token, 1)[-1]
        if not session_key:
            continue
        store = SessionStore(session_key=session_key)
        try:
            store.load()
            if store._session:
                yield store._session, store.get_expiry_date()
        except Exception:
            continue


def _iter_active_session_data():
    engine = settings.SESSION_ENGINE
    if engine == "django.contrib.sessions.backends.cache":
        yield from _iter_cache_backed_session_data()
        return
    yield from _iter_database_session_data()


def _active_user_sessions():
    from apps.employees.live_sessions import (
        LIVE_SESSION_WINDOW,
        format_last_seen,
        is_live_session,
        session_last_activity,
    )

    cached = cache.get(ACTIVE_SESSIONS_CACHE_KEY)
    if cached is not None:
        return cached

    employee_auth = {}
    student_auth = {}
    parent_auth = {}
    sessions_scanned = 0
    live_sessions = 0

    for data, expire_date in _iter_active_session_data():
        sessions_scanned += 1
        if not is_live_session(data, expire_date):
            continue
        live_sessions += 1
        last_activity = session_last_activity(data, expire_date)

        auth_user_id = data.get("_auth_user_id")
        if auth_user_id:
            employee_id = int(auth_user_id)
            entry = employee_auth.setdefault(
                employee_id,
                {"devices": 0, "roles": set(), "last_seen": None},
            )
            entry["devices"] += 1
            active_role = data.get("active_workspace_role") or data.get("workspace_role")
            if active_role:
                entry["roles"].add(active_role)
            if entry["last_seen"] is None or last_activity > entry["last_seen"]:
                entry["last_seen"] = last_activity

        student_id = data.get("student_id")
        if student_id:
            student_id = int(student_id)
            entry = student_auth.setdefault(
                student_id,
                {"devices": 0, "last_seen": None},
            )
            entry["devices"] += 1
            if entry["last_seen"] is None or last_activity > entry["last_seen"]:
                entry["last_seen"] = last_activity

        parent_id = data.get("parent_id")
        if parent_id:
            parent_id = int(parent_id)
            entry = parent_auth.setdefault(
                parent_id,
                {"devices": 0, "last_seen": None},
            )
            entry["devices"] += 1
            if entry["last_seen"] is None or last_activity > entry["last_seen"]:
                entry["last_seen"] = last_activity

    from apps.admissions.models import ParentGuardian, Student
    from apps.employees.models import Employee

    role_labels = dict(Employee.Role.choices)
    employees = []
    if employee_auth:
        for employee in Employee.objects.filter(pk__in=employee_auth.keys()).order_by(
            "last_name", "first_name"
        ):
            meta = employee_auth[employee.pk]
            roles = sorted(meta["roles"])
            if len(roles) == 1:
                role_display = role_labels.get(roles[0], roles[0])
            elif roles:
                role_display = ", ".join(role_labels.get(role, role) for role in roles)
            else:
                role_display = role_labels.get(employee.role, employee.role)
            employees.append(
                {
                    "id": employee.pk,
                    "name": employee.display_name,
                    "employee_code": employee.employee_code,
                    "role": role_display,
                    "devices": meta["devices"],
                    "last_seen": meta["last_seen"].isoformat() if meta["last_seen"] else None,
                    "last_seen_display": format_last_seen(meta["last_seen"]),
                }
            )
        employees.sort(
            key=lambda row: row["last_seen"] or "",
            reverse=True,
        )

    students = []
    if student_auth:
        for student in Student.objects.filter(pk__in=student_auth.keys()).order_by(
            "last_name", "first_name"
        ):
            meta = student_auth[student.pk]
            students.append(
                {
                    "id": student.pk,
                    "name": student.display_name,
                    "admission_number": student.admission_number or "—",
                    "class_group": student.class_group or "—",
                    "is_active": student.is_active,
                    "is_suspended": student.is_suspended,
                    "devices": meta["devices"],
                    "last_seen": meta["last_seen"].isoformat() if meta["last_seen"] else None,
                    "last_seen_display": format_last_seen(meta["last_seen"]),
                }
            )
        students.sort(key=lambda row: row["last_seen"] or "", reverse=True)

    parents = []
    if parent_auth:
        for parent in (
            ParentGuardian.objects.filter(pk__in=parent_auth.keys())
            .annotate(children_count=Count("students"))
            .order_by("full_name")
        ):
            meta = parent_auth[parent.pk]
            parents.append(
                {
                    "id": parent.pk,
                    "name": parent.full_name,
                    "phone_number": parent.phone_number,
                    "children": parent.children_count,
                    "is_active": parent.is_active,
                    "devices": meta["devices"],
                    "last_seen": meta["last_seen"].isoformat() if meta["last_seen"] else None,
                    "last_seen_display": format_last_seen(meta["last_seen"]),
                }
            )
        parents.sort(key=lambda row: row["last_seen"] or "", reverse=True)

    result = {
        "employees": employees[:MAX_SESSION_USERS_LISTED],
        "students": students[:MAX_SESSION_USERS_LISTED],
        "parents": parents[:MAX_SESSION_USERS_LISTED],
        "totals": {
            "employees": len(employees),
            "students": len(students),
            "parents": len(parents),
            "sessions_scanned": sessions_scanned,
            "live_sessions": live_sessions,
        },
        "window_minutes": int(LIVE_SESSION_WINDOW.total_seconds() // 60),
        "truncated": {
            "employees": len(employees) > MAX_SESSION_USERS_LISTED,
            "students": len(students) > MAX_SESSION_USERS_LISTED,
            "parents": len(parents) > MAX_SESSION_USERS_LISTED,
        },
    }
    cache.set(ACTIVE_SESSIONS_CACHE_KEY, result, ACTIVE_SESSIONS_CACHE_TTL)
    return result


def _measure_db_ms():
    start = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        elapsed = (time.perf_counter() - start) * 1000
        return {"status": "ok", "latency_ms": round(elapsed, 1)}
    except Exception as exc:
        return {"status": "error", "latency_ms": None, "error": str(exc)[:120]}


def _measure_cache_ms():
    start = time.perf_counter()
    try:
        cache.set(PROBE_CACHE_KEY, "1", 5)
        if cache.get(PROBE_CACHE_KEY) != "1":
            raise RuntimeError("Cache read/write mismatch")
        elapsed = (time.perf_counter() - start) * 1000
        return {"status": "ok", "latency_ms": round(elapsed, 1)}
    except Exception as exc:
        return {"status": "error", "latency_ms": None, "error": str(exc)[:120]}


def _disk_usage(path):
    usage = shutil.disk_usage(path)
    used_pct = round((usage.used / usage.total) * 100, 1) if usage.total else 0
    gb = 1024**3
    return {
        "path": str(Path(path)),
        "total_gb": round(usage.total / gb, 2),
        "used_gb": round(usage.used / gb, 2),
        "free_gb": round(usage.free / gb, 2),
        "used_pct": used_pct,
    }


def _storage_layout():
    media_root = Path(settings.MEDIA_ROOT)
    project_root = Path(settings.BASE_DIR)
    return {
        "media": _disk_usage(media_root if media_root.exists() else project_root),
        "project": _disk_usage(project_root),
    }


def _database_info():
    cached = cache.get(DB_INFO_CACHE_KEY)
    if cached is not None:
        return cached

    db_settings = settings.DATABASES["default"]
    info = {
        "name": str(db_settings.get("NAME", "")),
        "host": db_settings.get("HOST") or "localhost",
        "port": str(db_settings.get("PORT") or ""),
        "engine": connection.vendor,
        "conn_max_age": db_settings.get("CONN_MAX_AGE", 0),
        "version": "",
        "size_mb": None,
        "table_count": 0,
    }
    try:
        with connection.cursor() as cursor:
            if connection.vendor == "mysql":
                cursor.execute("SELECT VERSION()")
                info["version"] = cursor.fetchone()[0]
                cursor.execute(
                    """
                    SELECT COUNT(*),
                           ROUND(COALESCE(SUM(data_length + index_length), 0) / 1024 / 1024, 2)
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                    """
                )
                table_count, size_mb = cursor.fetchone()
                info["table_count"] = int(table_count or 0)
                info["size_mb"] = float(size_mb or 0)
            elif connection.vendor == "sqlite":
                cursor.execute("SELECT sqlite_version()")
                info["version"] = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                info["table_count"] = int(cursor.fetchone()[0] or 0)
                db_path = Path(str(db_settings.get("NAME", "")))
                if db_path.exists():
                    info["size_mb"] = round(db_path.stat().st_size / (1024**2), 2)
    except Exception:
        pass

    cache.set(DB_INFO_CACHE_KEY, info, DB_INFO_CACHE_TTL)
    return info


def _top_database_tables():
    cached = cache.get(TABLES_CACHE_KEY)
    if cached is not None:
        return cached

    tables = []
    try:
        with connection.cursor() as cursor:
            if connection.vendor == "mysql":
                cursor.execute(
                    """
                    SELECT table_name,
                           COALESCE(table_rows, 0),
                           ROUND(COALESCE(data_length + index_length, 0) / 1024 / 1024, 2)
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                    ORDER BY data_length + index_length DESC
                    LIMIT 8
                    """
                )
                tables = [
                    {"name": row[0], "rows": int(row[1] or 0), "size_mb": float(row[2] or 0)}
                    for row in cursor.fetchall()
                ]
            elif connection.vendor == "sqlite":
                cursor.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                    LIMIT 8
                    """
                )
                for (name,) in cursor.fetchall():
                    cursor.execute(f'SELECT COUNT(*) FROM "{name}"')
                    tables.append(
                        {
                            "name": name,
                            "rows": int(cursor.fetchone()[0] or 0),
                            "size_mb": None,
                        }
                    )
    except Exception:
        tables = []

    cache.set(TABLES_CACHE_KEY, tables, TABLES_CACHE_TTL)
    return tables


def _media_storage():
    cached = cache.get(MEDIA_CACHE_KEY)
    if cached is not None:
        return cached

    media_root = Path(settings.MEDIA_ROOT)
    total_bytes = 0
    file_count = 0
    partial = False
    if media_root.exists():
        for path in media_root.rglob("*"):
            if not path.is_file():
                continue
            try:
                total_bytes += path.stat().st_size
                file_count += 1
            except OSError:
                continue
            if file_count >= 5000:
                partial = True
                break

    result = {
        "path": str(media_root),
        "bytes": total_bytes,
        "mb": round(total_bytes / (1024**2), 2),
        "files": file_count,
        "partial": partial,
    }
    cache.set(MEDIA_CACHE_KEY, result, MEDIA_CACHE_TTL)
    return result


def _entity_counts():
    cached = cache.get(COUNTS_CACHE_KEY)
    if cached is not None:
        return cached

    from apps.admissions.models import ParentGuardian, Student
    from apps.curriculum.models import (
        AcademicClass,
        ClassAttendanceSession,
        GeneratedExamTimetable,
        LearningArea,
    )
    from apps.employees.models import Employee

    counts = {
        "students_active": Student.objects.filter(is_active=True).count(),
        "students_inactive": Student.objects.filter(is_active=False).count(),
        "students_total": Student.objects.count(),
        "parents_total": ParentGuardian.objects.count(),
        "employees_active": Employee.objects.filter(
            is_active=True,
            approval_status=Employee.ApprovalStatus.APPROVED,
        ).count(),
        "employees_pending": Employee.objects.filter(
            approval_status=Employee.ApprovalStatus.PENDING_APPROVAL
        ).count(),
        "employees_total": Employee.objects.count(),
        "classes_active": AcademicClass.objects.filter(
            status=AcademicClass.Status.ACTIVE
        ).count(),
        "learning_areas": LearningArea.objects.count(),
        "exam_generations": GeneratedExamTimetable.objects.count(),
        "attendance_sessions": ClassAttendanceSession.objects.count(),
    }
    cache.set(COUNTS_CACHE_KEY, counts, COUNTS_CACHE_TTL)
    return counts


def _operational_metrics():
    cached = cache.get(OPERATIONS_CACHE_KEY)
    if cached is not None:
        return cached

    from apps.admissions.models import Student
    from apps.curriculum.models import ClassAttendanceSession
    from apps.employees.models import Employee

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    week_ago = timezone.localdate() - timedelta(days=7)

    metrics = {
        "students_admitted_this_month": Student.objects.filter(
            admitted_at__gte=month_start
        ).count(),
        "attendance_sessions_this_week": ClassAttendanceSession.objects.filter(
            attendance_date__gte=week_ago
        ).count(),
        "employees_suspended": Employee.objects.filter(is_active=False).count(),
        "portal_ready_students": Student.objects.filter(
            is_active=True, is_suspended=False
        ).count(),
    }
    cache.set(OPERATIONS_CACHE_KEY, metrics, OPERATIONS_CACHE_TTL)
    return metrics


def _record_metrics_sample(database, cache_info, storage, active_sessions):
    history = cache.get(LATENCY_HISTORY_KEY) or []
    media = storage.get("media") or {}
    totals = active_sessions.get("totals") or {}
    sessions_total = (
        (totals.get("employees") or 0)
        + (totals.get("students") or 0)
        + (totals.get("parents") or 0)
    )
    history.append(
        {
            "at": timezone.now().isoformat(),
            "db_ms": database.get("latency_ms") or 0 if database.get("status") == "ok" else 0,
            "cache_ms": cache_info.get("latency_ms") or 0 if cache_info.get("status") == "ok" else 0,
            "disk_pct": media.get("used_pct") or 0,
            "sessions_total": sessions_total,
        }
    )
    cache.set(LATENCY_HISTORY_KEY, history[-LATENCY_HISTORY_MAX:], 3600)


def _build_sparkline(values, *, width=88, height=28, pad=2):
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    if len(cleaned) == 1:
        cleaned = [cleaned[0], cleaned[0]]
    min_value = min(cleaned)
    max_value = max(cleaned)
    span = max(max_value - min_value, 1)
    plot_width = width - pad * 2
    plot_height = height - pad * 2
    points = []
    for index, value in enumerate(cleaned):
        x = pad + (index / (len(cleaned) - 1)) * plot_width
        y = pad + plot_height - ((value - min_value) / span) * plot_height
        points.append({"x": round(x, 1), "y": round(y, 1)})
    line = " ".join(f"{point['x']},{point['y']}" for point in points)
    area = f"{pad},{height - pad} {line} {width - pad},{height - pad}"
    return {"width": width, "height": height, "line": line, "area": area, "points": points}


def _kpi_trends(history):
    return {
        "db": _build_sparkline([point.get("db_ms") for point in history]),
        "cache": _build_sparkline([point.get("cache_ms") for point in history]),
        "disk": _build_sparkline([point.get("disk_pct") for point in history]),
        "sessions": _build_sparkline([point.get("sessions_total") for point in history]),
    }


def _large_trend_cards(history):
    cards = (
        ("db", "Database latency", "ms", "is-db"),
        ("cache", "Cache latency", "ms", "is-cache"),
        ("disk", "Disk usage", "%", "is-disk"),
        ("sessions", "Active sessions", "users", "is-users"),
    )
    key_map = {
        "db": "db_ms",
        "cache": "cache_ms",
        "disk": "disk_pct",
        "sessions": "sessions_total",
    }
    result = []
    for slug, label, unit, tone in cards:
        key = key_map[slug]
        values = [point.get(key) for point in history]
        latest = values[-1] if values else None
        result.append(
            {
                "slug": slug,
                "label": label,
                "unit": unit,
                "tone": tone,
                "latest": latest,
                "delta": _metric_delta(values),
                "trend": _build_sparkline(values, width=220, height=56, pad=4),
            }
        )
    return result


def _metric_delta(values):
    cleaned = [value for value in values if value is not None]
    if len(cleaned) < 2:
        return {"direction": "flat", "value": 0}
    previous, current = cleaned[-2], cleaned[-1]
    diff = round(current - previous, 1)
    if diff == 0:
        return {"direction": "flat", "value": 0}
    return {"direction": "up" if diff > 0 else "down", "value": abs(diff)}


def _kpi_deltas(history):
    if len(history) < 2:
        return {}
    keys = ("db_ms", "cache_ms", "disk_pct", "sessions_total")
    return {
        key: _metric_delta([point.get(key) for point in history])
        for key in keys
    }


def _build_dual_line_chart(history, *, width=560, height=180):
    if not history:
        return None

    db_values = [point.get("db_ms") or 0 for point in history]
    cache_values = [point.get("cache_ms") or 0 for point in history]
    max_value = max([*db_values, *cache_values, 10])
    pad_left = 38
    pad_right = 14
    pad_top = 14
    pad_bottom = 28
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom
    baseline_y = height - pad_bottom

    def series_points(values):
        if len(values) == 1:
            values = [values[0], values[0]]
        points = []
        for index, value in enumerate(values):
            x = pad_left + (index / (len(values) - 1)) * plot_width
            y = pad_top + plot_height - (value / max_value) * plot_height
            points.append({"x": round(x, 1), "y": round(y, 1), "value": value})
        line = " ".join(f"{point['x']},{point['y']}" for point in points)
        area = f"{pad_left},{baseline_y} {line} {width - pad_right},{baseline_y}"
        return points, line, area

    db_points, db_line, db_area = series_points(db_values)
    cache_points, cache_line, cache_area = series_points(cache_values)
    grid = []
    for tick in range(5):
        value = round(max_value - (max_value / 4) * tick, 1)
        y = pad_top + (plot_height / 4) * tick
        grid.append({"y": round(y, 1), "value": value})

    return {
        "width": width,
        "height": height,
        "plot_left": pad_left,
        "plot_right": width - pad_right,
        "baseline_y": baseline_y,
        "grid": grid,
        "db": {"line": db_line, "area": db_area, "points": db_points},
        "cache": {"line": cache_line, "area": cache_area, "points": cache_points},
    }


def _health_summary(status, database, cache_info, storage, active_sessions):
    media = storage.get("media") or {}
    totals = active_sessions.get("totals") or {}
    total_users = (
        (totals.get("employees") or 0)
        + (totals.get("students") or 0)
        + (totals.get("parents") or 0)
    )
    score = 96
    if status == "degraded":
        score = 72
    elif status == "critical":
        score = 38

    db_ms = database.get("latency_ms") or 0
    cache_ms = cache_info.get("latency_ms") or 0
    disk_pct = media.get("used_pct") or 0
    score -= min(18, round(db_ms / 12))
    score -= min(12, round(cache_ms / 8))
    score -= min(20, round(disk_pct / 5))
    score = max(8, min(100, round(score)))

    ring = 2 * 3.141592653589793 * 42
    dash = round((score / 100) * ring, 2)
    label = "Healthy"
    tone = "is-ok"
    if status == "degraded":
        label = "Degraded"
        tone = "is-warn"
    elif status == "critical":
        label = "Critical"
        tone = "is-bad"

    return {
        "score": score,
        "label": label,
        "tone": tone,
        "ring": round(ring, 2),
        "dash": dash,
        "gap": round(ring - dash, 2),
        "active_users": total_users,
        "disk_pct": disk_pct,
        "db_ms": db_ms if database.get("status") == "ok" else None,
        "cache_ms": cache_ms if cache_info.get("status") == "ok" else None,
    }


def _enrich_tables(tables):
    if not tables:
        return []
    max_rows = max(table.get("rows") or 0 for table in tables) or 1
    enriched = []
    for table in tables:
        rows = table.get("rows") or 0
        enriched.append(
            {
                **table,
                "bar_pct": min(100, round((rows / max_rows) * 100)),
            }
        )
    return enriched


def _stress_score_chart(events):
    scores = [event.get("score") or 0 for event in reversed(events[-12:])]
    return _build_sparkline(scores, width=220, height=56, pad=4)


def _latency_history():
    history = cache.get(LATENCY_HISTORY_KEY) or []
    if not history:
        return []
    max_ms = max(
        [point.get("db_ms", 0) for point in history]
        + [point.get("cache_ms", 0) for point in history]
        + [50]
    )
    scaled = []
    for point in history:
        db_ms = point.get("db_ms") or 0
        cache_ms = point.get("cache_ms") or 0
        scaled.append(
            {
                **point,
                "db_height": min(100, round((db_ms / max_ms) * 100)),
                "cache_height": min(100, round((cache_ms / max_ms) * 100)),
            }
        )
    return scaled


def _latency_summary(history):
    if not history:
        return {"db_avg_ms": None, "cache_avg_ms": None, "samples": 0}
    db_values = [point["db_ms"] for point in history if point.get("db_ms") is not None]
    cache_values = [
        point["cache_ms"] for point in history if point.get("cache_ms") is not None
    ]
    return {
        "db_avg_ms": round(sum(db_values) / len(db_values), 1) if db_values else None,
        "cache_avg_ms": round(sum(cache_values) / len(cache_values), 1)
        if cache_values
        else None,
        "samples": len(history),
    }


def _app_info():
    cache_backend = settings.CACHES["default"]["BACKEND"]
    session_engine = getattr(settings, "SESSION_ENGINE", "").rsplit(".", 1)[-1]
    return {
        "debug": settings.DEBUG,
        "timezone": str(settings.TIME_ZONE),
        "django_version": django.get_version(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "database_engine": connection.vendor,
        "cache_backend": cache_backend.rsplit(".", 1)[-1],
        "session_engine": session_engine or "unknown",
        "allowed_hosts_count": len(getattr(settings, "ALLOWED_HOSTS", [])),
        "redis_enabled": "redis" in cache_backend.lower(),
    }


def _overall_status(database, cache_info, storage):
    media = storage["media"]
    if database["status"] != "ok" or cache_info["status"] != "ok":
        return "critical"
    if media["used_pct"] >= 90:
        return "critical"
    db_ms = database.get("latency_ms") or 0
    cache_ms = cache_info.get("latency_ms") or 0
    if media["used_pct"] >= 80 or db_ms >= 200 or cache_ms >= 100:
        return "degraded"
    if db_ms >= 100 or cache_ms >= 50:
        return "degraded"
    return "healthy"


def _stress_severity(score, status):
    if status == "critical" or score >= 80:
        return "critical"
    if status == "degraded" or score >= 50:
        return "degraded"
    return "elevated"


def _stress_reasons(database, cache_info, storage, active_sessions, status):
    reasons = []
    media = storage["media"]
    db_ms = database.get("latency_ms") or 0
    cache_ms = cache_info.get("latency_ms") or 0
    totals = active_sessions.get("totals", {})
    total_users = (
        totals.get("employees", 0)
        + totals.get("students", 0)
        + totals.get("parents", 0)
    )
    sessions_scanned = totals.get("sessions_scanned", 0)

    if database.get("status") != "ok":
        reasons.append(
            {
                "code": "database_down",
                "label": "Database unavailable",
                "detail": database.get("error", "Connection failed"),
            }
        )
    elif db_ms >= 100:
        reasons.append(
            {
                "code": "db_slow",
                "label": "Slow database response",
                "detail": f"{db_ms} ms probe latency",
            }
        )

    if cache_info.get("status") != "ok":
        reasons.append(
            {
                "code": "cache_down",
                "label": "Cache unavailable",
                "detail": cache_info.get("error", "Read/write failed"),
            }
        )
    elif cache_ms >= 50:
        reasons.append(
            {
                "code": "cache_slow",
                "label": "Slow cache response",
                "detail": f"{cache_ms} ms probe latency",
            }
        )

    if media["used_pct"] >= 90:
        reasons.append(
            {
                "code": "disk_critical",
                "label": "Critical disk usage",
                "detail": f"{media['used_pct']}% used on storage volume",
            }
        )
    elif media["used_pct"] >= 80:
        reasons.append(
            {
                "code": "disk_pressure",
                "label": "High disk usage",
                "detail": f"{media['used_pct']}% used on storage volume",
            }
        )

    if total_users >= 15:
        reasons.append(
            {
                "code": "high_concurrency",
                "label": "High concurrent users",
                "detail": f"{total_users} users across {sessions_scanned} active sessions",
            }
        )
    elif total_users >= 8:
        reasons.append(
            {
                "code": "elevated_concurrency",
                "label": "Elevated concurrent users",
                "detail": f"{total_users} users currently in session",
            }
        )

    if status != "healthy" and not reasons:
        reasons.append(
            {
                "code": "degraded",
                "label": "System performance degraded",
                "detail": "Multiple health thresholds were exceeded",
            }
        )

    return reasons


def _stress_score(database, cache_info, storage, active_sessions, status):
    score = 0.0
    db_ms = database.get("latency_ms") or 0
    cache_ms = cache_info.get("latency_ms") or 0
    media = storage["media"]
    totals = active_sessions.get("totals", {})
    total_users = (
        totals.get("employees", 0)
        + totals.get("students", 0)
        + totals.get("parents", 0)
    )

    if database.get("status") != "ok":
        score += 100
    else:
        score += min(50, db_ms / 4)

    if cache_info.get("status") != "ok":
        score += 40
    else:
        score += min(30, cache_ms / 2)

    score += min(25, media["used_pct"] / 4)
    score += min(25, total_users * 1.5)

    if status == "critical":
        score += 30
    elif status == "degraded":
        score += 15

    return round(score, 1)


def _stress_summary(reasons, active_sessions):
    labels = [reason["label"] for reason in reasons[:3]]
    totals = active_sessions.get("totals", {})
    users = (
        f"{totals.get('employees', 0)} staff, "
        f"{totals.get('students', 0)} students, "
        f"{totals.get('parents', 0)} parents online"
    )
    if labels:
        return f"{'; '.join(labels)}. {users}."
    return f"System load increased. {users}."


def _session_snapshot(active_sessions):
    return {
        "totals": active_sessions.get("totals", {}),
        "employees": active_sessions.get("employees", [])[:STRESS_SESSION_SAMPLE],
        "students": active_sessions.get("students", [])[:STRESS_SESSION_SAMPLE],
        "parents": active_sessions.get("parents", [])[:STRESS_SESSION_SAMPLE],
        "truncated": active_sessions.get("truncated", {}),
    }


def _should_record_stress_event(score, status, reasons):
    if status == "healthy" and score < 30:
        return False
    if not reasons and score < 35:
        return False
    return True


def _record_stress_event(
    *,
    collected_at,
    status,
    database,
    cache_info,
    storage,
    active_sessions,
):
    score = _stress_score(database, cache_info, storage, active_sessions, status)
    reasons = _stress_reasons(database, cache_info, storage, active_sessions, status)
    if not _should_record_stress_event(score, status, reasons):
        return

    last_record = cache.get(STRESS_RECORD_COOLDOWN_KEY)
    if last_record:
        last_at = last_record.get("at")
        last_score = last_record.get("score", 0)
        if last_at:
            try:
                last_time = timezone.datetime.fromisoformat(last_at)
                if timezone.is_naive(last_time):
                    last_time = timezone.make_aware(last_time)
                elapsed = (collected_at - last_time).total_seconds()
            except (TypeError, ValueError):
                elapsed = STRESS_RECORD_COOLDOWN_SEC
            if elapsed < STRESS_RECORD_COOLDOWN_SEC and score < last_score * 1.15:
                return

    severity = _stress_severity(score, status)
    media = storage["media"]
    event = {
        "at": collected_at.isoformat(),
        "severity": severity,
        "score": score,
        "summary": _stress_summary(reasons, active_sessions),
        "reasons": reasons,
        "metrics": {
            "db_ms": database.get("latency_ms"),
            "cache_ms": cache_info.get("latency_ms"),
            "disk_pct": media.get("used_pct"),
            "sessions_scanned": active_sessions.get("totals", {}).get("sessions_scanned", 0),
        },
        "sessions": _session_snapshot(active_sessions),
    }

    events = cache.get(STRESS_EVENTS_KEY) or []
    events.insert(0, event)
    cache.set(STRESS_EVENTS_KEY, events[:STRESS_EVENTS_MAX], STRESS_EVENTS_TTL)
    cache.set(
        STRESS_RECORD_COOLDOWN_KEY,
        {"at": collected_at.isoformat(), "score": score},
        STRESS_RECORD_COOLDOWN_SEC * 2,
    )


def _format_event_time(at_value):
    if not at_value:
        return "—"
    try:
        parsed = timezone.datetime.fromisoformat(at_value)
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return timezone.localtime(parsed).strftime("%b %d, %Y %I:%M:%S %p")
    except (TypeError, ValueError):
        return str(at_value)


def _stress_timeline():
    events = cache.get(STRESS_EVENTS_KEY) or []
    if not events:
        return {"events": [], "peak": None, "peak_score": None}

    peak = max(events, key=lambda event: event.get("score", 0))
    peak_score = peak.get("score")
    peak_at = peak.get("at")
    enriched = []
    for event in events:
        enriched.append(
            {
                **event,
                "at_display": _format_event_time(event.get("at")),
                "is_peak": event.get("at") == peak_at and event.get("score") == peak_score,
            }
        )
    enriched.sort(key=lambda event: event.get("at", ""), reverse=True)
    peak_event = next((event for event in enriched if event.get("is_peak")), enriched[0])
    return {
        "events": enriched,
        "peak": peak_event,
        "peak_score": peak_score,
    }


def get_system_performance_snapshot(*, include_counts=True):
    database = _measure_db_ms()
    cache_info = _measure_cache_ms()
    storage = _storage_layout()
    db_info = _database_info()
    active_sessions = _active_user_sessions()
    _record_metrics_sample(database, cache_info, storage, active_sessions)
    history = _latency_history()

    database = {**database, **db_info}
    counts = _entity_counts() if include_counts else {}
    operations = _operational_metrics() if include_counts else {}
    collected_at = timezone.now()
    status = _overall_status(database, cache_info, storage)
    _record_stress_event(
        collected_at=collected_at,
        status=status,
        database=database,
        cache_info=cache_info,
        storage=storage,
        active_sessions=active_sessions,
    )
    stress_timeline = _stress_timeline()
    tables = _enrich_tables(_top_database_tables())

    snapshot = {
        "status": status,
        "health": _health_summary(status, database, cache_info, storage, active_sessions),
        "database": database,
        "cache": cache_info,
        "storage": storage,
        "media": _media_storage(),
        "counts": counts,
        "operations": operations,
        "tables": tables,
        "latency": {
            "history": history,
            "summary": _latency_summary(history),
            "chart": _build_dual_line_chart(history),
        },
        "kpi_trends": _kpi_trends(history),
        "kpi_deltas": _kpi_deltas(history),
        "trend_cards": _large_trend_cards(history),
        "active_sessions": active_sessions,
        "stress_timeline": {
            **stress_timeline,
            "score_chart": _stress_score_chart(stress_timeline.get("events") or []),
        },
        "app": _app_info(),
        "collected_at": collected_at,
    }
    return snapshot
