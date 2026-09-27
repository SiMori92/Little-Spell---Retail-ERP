"""Validate and optionally commit a complete supplier-master snapshot."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ops.file_intake import import_suppliers
from ops.intake import ImportRefused


class Command(BaseCommand):
    help = "Validate inbox/suppliers CSV; dry-run unless --commit is supplied."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=Path, required=True)
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        try:
            result = import_suppliers(options["file"], commit=options["commit"])
        except (ImportRefused, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Supplier rows parsed: {result.parsed_rows}; rows that would be written: {result.would_write_rows}"
            if not options["commit"] else
            f"Supplier rows parsed: {result.parsed_rows}; rows inserted: {result.inserted_rows}"
        )
