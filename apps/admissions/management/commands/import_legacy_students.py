from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.admissions.legacy_import import import_legacy_students, parse_legacy_student_rows


class Command(BaseCommand):
    help = "Import students from a phpMyAdmin students SQL dump into Educentric."

    def add_arguments(self, parser):
        parser.add_argument("sql_path", type=str, help="Path to the students SQL dump")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse the dump and report counts without writing to the database",
        )

    def handle(self, *args, **options):
        path = Path(options["sql_path"])
        if not path.exists():
            raise CommandError(f"SQL file not found: {path}")

        sql_text = path.read_text(encoding="utf-8", errors="replace")
        if options["dry_run"]:
            rows = parse_legacy_student_rows(sql_text)
            self.stdout.write(f"Parsed {len(rows)} student rows. No database changes made.")
            return

        with transaction.atomic():
            result = import_legacy_students(sql_text)
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {result['created']} students "
                f"({result['skipped']} already present, {result['parsed']} parsed)."
            )
        )
