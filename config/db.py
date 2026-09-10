"""MySQL connection helpers for local XAMPP and cPanel shared hosting."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Shared hosting often exposes MySQL only via a Unix socket. PyMySQL uses TCP
# for "localhost" unless unix_socket is set — which yields Errno 111.
_COMMON_MYSQL_SOCKETS = (
    "/var/lib/mysql/mysql.sock",
    "/tmp/mysql.sock",
    "/var/run/mysqld/mysqld.sock",
    "/run/mysqld/mysqld.sock",
    "/usr/local/mysql/mysql.sock",
    "/Applications/XAMPP/xamppfiles/var/mysql/mysql.sock",
)


def _looks_like_socket(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    return value.startswith("/") or value.endswith(".sock")


def _first_existing_socket(candidates: list[str]) -> str | None:
    for raw in candidates:
        path = raw.strip()
        if not path:
            continue
        p = Path(path)
        try:
            if p.is_socket():
                return path
        except OSError:
            continue
        # Some hosts expose a usable sock path that is_socket() misses.
        if path.endswith(".sock") and p.exists():
            return path
    return None


def discover_mysql_socket(explicit: str = "") -> str | None:
    """Return a usable MySQL Unix socket path, or None on Windows / if none found."""
    if os.name == "nt":
        return None

    candidates: list[str] = []
    if explicit.strip():
        candidates.append(explicit.strip())

    env_socket = os.environ.get("DB_SOCKET", "").strip()
    if env_socket:
        candidates.append(env_socket)

    # Some hosts export this for CLI clients; reuse when present.
    for key in ("MYSQL_UNIX_PORT", "MYSQL_SOCKET"):
        value = os.environ.get(key, "").strip()
        if value:
            candidates.append(value)

    candidates.extend(_COMMON_MYSQL_SOCKETS)
    return _first_existing_socket(candidates)


def build_mysql_database(
    *,
    name: str,
    user: str,
    password: str,
    host: str,
    port: str,
    conn_max_age: int,
    socket: str = "",
) -> dict[str, Any]:
    """Build DATABASES['default'] with cPanel-safe socket / TCP resolution."""
    options: dict[str, Any] = {
        "charset": "utf8mb4",
        "connect_timeout": 10,
        "read_timeout": 60,
        "write_timeout": 60,
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
    }

    host = (host or "").strip()
    port = (port or "").strip()
    socket = (socket or "").strip()

    # Explicit socket path as HOST (Django convention) or DB_SOCKET.
    if _looks_like_socket(host):
        socket = host
        host = "localhost"
        port = ""
    elif socket:
        host = host or "localhost"
        port = ""
    elif host.lower() in {"", "localhost", "127.0.0.1"}:
        # Prefer Unix socket when available (cPanel / many Linux hosts).
        found = discover_mysql_socket()
        if found:
            socket = found
            host = "localhost"
            port = ""
            logger.info("MySQL: using Unix socket %s", socket)
        else:
            host = host or "127.0.0.1"
            port = port or "3306"

    if socket:
        options["unix_socket"] = socket
        # Django also accepts HOST=/path/to.sock; keep both for PyMySQL + Django.
        if _looks_like_socket(socket):
            host = socket
            port = ""

    return {
        "ENGINE": "config.mysql_backend",
        "NAME": name,
        "USER": user,
        "PASSWORD": password,
        "HOST": host,
        "PORT": port,
        "CONN_MAX_AGE": conn_max_age,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": options,
    }
