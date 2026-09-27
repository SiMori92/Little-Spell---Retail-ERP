"""Validate and optionally commit one supplier-payment row (Slice G-3)."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ops.intake import ImportRefused
from ops.payments import import_supplier_payment


class Command(BaseCommand):
    help = "Validate one inbox/po_payments supplier payment CSV; dry-run unless --commit is supplied."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=Path, required=True)
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        try:
            result = import_supplier_payment(options["file"], commit=options["commit"])
        except (ImportRefused, OSError) as exc:
            raise CommandError(str(exc)) from exc
        if not options["commit"]:
            self.stdout.write(f"rows parsed: {result.parsed_rows}; rows that would be written: "
                              f"{result.would_write_rows}")
            return
        self.stdout.write(f"rows parsed: {result.parsed_rows}; rows inserted: {result.inserted_rows}; "
                          f"po.paid events: {result.inserted_events}")
