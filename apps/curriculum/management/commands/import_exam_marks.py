from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.curriculum.exam_marks_import import import_exam_marks_csv


class Command(BaseCommand):
    help = (
        "Import student assessment marks from a CSV export. Creates missing exam shells when needed, "
        "and only inserts marks that do not already exist."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to the assessment marks CSV file")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report counts without writing to the database",
        )

    def handle(self, *args, **options):
        path = Path(options["csv_path"])
        if not path.exists():
            raise CommandError(f"CSV file not found: {path}")

        if options["dry_run"]:
            result = import_exam_marks_csv(path, dry_run=True)
        else:
            with transaction.atomic():
                result = import_exam_marks_csv(path, dry_run=False)

        self.stdout.write(
            self.style.SUCCESS(
                f"Parsed {result['parsed']} rows | "
                f"created exams {result['created_exams']} | "
                f"reused exams {result['reused_exams']} | "
                f"inserted marks {result['created_marks']} | "
                f"skipped existing {result['skipped_existing']} | "
                f"rounded {result['rounded_marks']}"
            )
        )
        for label, key in (
            ("missing students", "skipped_missing_student"),
            ("missing subjects", "skipped_missing_subject"),
            ("missing years", "skipped_missing_year"),
            ("missing terms", "skipped_missing_term"),
            ("invalid marks", "skipped_invalid_marks"),
        ):
            if result[key]:
                self.stdout.write(f"  skipped {label}: {result[key]}")

        for label, key in (
            ("students", "missing_students"),
            ("subjects", "missing_subjects"),
            ("years", "missing_years"),
            ("terms", "missing_terms"),
        ):
            values = result.get(key) or []
            if values:
                preview = ", ".join(values[:12])
                more = f" (+{len(values) - 12} more)" if len(values) > 12 else ""
                self.stdout.write(f"  unmatched {label}: {preview}{more}")
