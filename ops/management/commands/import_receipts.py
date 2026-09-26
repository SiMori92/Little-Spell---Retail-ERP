"""Validate and optionally commit an evidenced TWD receipt CSV."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ops.file_intake import import_receipts
from ops.intake import ImportRefused


class Command(BaseCommand):
    help = "Validate inbox/receipts CSV; --commit requires a verified schema fixture."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=Path, required=True)
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        try:
            result = import_receipts(options["file"], commit=options["commit"])
        except (ImportRefused, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Receipt rows parsed: {result.parsed_rows}; rows inserted: {result.inserted_rows}; "
                          f"events emitted: {result.inserted_events}")
