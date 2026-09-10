"""Diagnose MySQL connectivity for cPanel / local deploys."""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from config.db import discover_mysql_socket


class Command(BaseCommand):
    help = "Print resolved MySQL settings and test a connection (safe for cPanel SSH)."

    def handle(self, *args, **options):
        db = settings.DATABASES.get("default", {})
        engine = db.get("ENGINE", "")
        if "mysql" not in engine and "mysql_backend" not in engine:
            self.stdout.write(
                self.style.WARNING(
                    f"Default DB engine is {engine!r} (SQLite?). "
                    "Set DB_NAME / DB_USER / DB_PASSWORD in .env for MySQL."
                )
            )
            return

        host = db.get("HOST", "")
        port = db.get("PORT", "")
        opts = db.get("OPTIONS") or {}
        socket = opts.get("unix_socket", "")
        discovered = discover_mysql_socket()

        self.stdout.write(f"NAME:   {db.get('NAME')}")
        self.stdout.write(f"USER:   {db.get('USER')}")
        self.stdout.write(f"HOST:   {host}")
        self.stdout.write(f"PORT:   {port or '(none)'}")
        self.stdout.write(f"SOCKET: {socket or '(none)'}")
        self.stdout.write(f"AUTO-DISCOVERED SOCKET: {discovered or '(none found)'}")

        try:
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            self.stdout.write(self.style.SUCCESS("MySQL connection OK"))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"MySQL connection FAILED: {exc}"))
            self.stderr.write(
                "Fix: in .env set DB_HOST to the host from cPanel → MySQL Databases, "
                "or set DB_SOCKET to an existing path (try /var/lib/mysql/mysql.sock "
                "or /tmp/mysql.sock). Then re-run: python manage.py check_mysql"
            )
            raise SystemExit(1) from exc
