"""Validate and optionally commit a complete physical-count CSV."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ops.file_intake import import_counts
from ops.intake import ImportRefused


class Command(BaseCommand):
    help = "Validate inbox/counts CSV; --commit requires a verified schema fixture."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=Path, required=True)
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        try:
            result = import_counts(options["file"], commit=options["commit"])
        except (ImportRefused, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Count SKU rows parsed: {result.parsed_rows}; rows inserted: {result.inserted_rows}; "
                          f"events emitted: {result.inserted_events}")
