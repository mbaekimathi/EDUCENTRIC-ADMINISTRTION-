"""Startup hooks that run when the web process loads."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_MIGRATIONS_APPLIED = False
_STAMP_NAME = ".auto_migrate_stamp"
_LOCK_NAME = ".auto_migrate.lock"
# Avoid hammering MySQL / Passenger on every worker spawn.
_STAMP_TTL_SECONDS = int(os.environ.get("AUTO_MIGRATE_TTL", "600"))


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _stamp_path() -> Path:
    return _base_dir() / _STAMP_NAME


def _lock_path() -> Path:
    return _base_dir() / _LOCK_NAME


def _stamp_is_fresh() -> bool:
    path = _stamp_path()
    if not path.exists():
        return False
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age < _STAMP_TTL_SECONDS


def _write_stamp() -> None:
    path = _stamp_path()
    try:
        path.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        logger.warning("Could not write auto-migrate stamp at %s", path)


def _acquire_lock() -> int | None:
    """Non-blocking exclusive lock file. Returns fd or None if busy/unavailable."""
    path = _lock_path()
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        # Stale lock older than TTL → steal it.
        try:
            if time.time() - path.stat().st_mtime > _STAMP_TTL_SECONDS:
                path.unlink(missing_ok=True)
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            else:
                return None
        except OSError:
            return None
    try:
        os.write(fd, str(os.getpid()).encode("ascii", "replace"))
    except OSError:
        pass
    return fd


def _release_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        _lock_path().unlink(missing_ok=True)
    except OSError:
        pass


def apply_pending_migrations() -> None:
    """Apply outstanding Django migrations when the app process starts.

    Controlled by AUTO_MIGRATE (default on). Never raises — on cPanel/Passenger
    a failed or killed migrate must not take the site down with WSGI import errors.
    """
    global _MIGRATIONS_APPLIED
    if _MIGRATIONS_APPLIED:
        return
    if not _env_flag("AUTO_MIGRATE", default=True):
        return

    argv = set(sys.argv)
    if argv & {"migrate", "makemigrations", "showmigrations", "test"}:
        return
    # Django's autoreloader spawns a parent + child; only migrate in the child.
    if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
        return

    if _stamp_is_fresh():
        _MIGRATIONS_APPLIED = True
        return

    lock_fd = _acquire_lock()
    if lock_fd is None:
        logger.info("Skipping AUTO_MIGRATE — another process holds the lock")
        return

    try:
        # Re-check after lock (winner may have finished).
        if _stamp_is_fresh():
            _MIGRATIONS_APPLIED = True
            return

        from django.db import close_old_connections, connection
        from django.core.management import call_command

        close_old_connections()
        # Force a fresh socket before migrate (avoids stale pooled pipes).
        connection.ensure_connection()

        logger.info("Applying database migrations (AUTO_MIGRATE)…")
        call_command("migrate", interactive=False, verbosity=1)
        _write_stamp()
        _MIGRATIONS_APPLIED = True
    except Exception:
        # Passenger often SIGTERMs long startups; MySQL may drop the pipe.
        # Keep the app online — run migrate via SSH/phpMyAdmin if needed.
        logger.exception(
            "AUTO_MIGRATE failed; app will continue without blocking startup"
        )
    finally:
        try:
            from django.db import close_old_connections

            close_old_connections()
        except Exception:
            pass
        _release_lock(lock_fd)
