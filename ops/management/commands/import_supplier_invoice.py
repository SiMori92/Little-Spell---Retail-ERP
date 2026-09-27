"""Validate and optionally commit one supplier invoice file (Slice G-2). A three-way match posts po.received."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ops.intake import ImportRefused
from ops.receiving import import_invoice


class Command(BaseCommand):
    help = "Validate one inbox/po_invoices/ supplier invoice CSV; dry-run unless --commit is supplied."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=Path, required=True)
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        try:
            result = import_invoice(options["file"], commit=options["commit"])
        except (ImportRefused, OSError) as exc:
            raise CommandError(str(exc)) from exc
        if not options["commit"]:
            self.stdout.write(f"lines parsed: {result.parsed_rows}; rows that would be written: "
                              f"{result.would_write_rows}")
            return
        self.stdout.write(f"lines parsed: {result.parsed_rows}; rows inserted: {result.inserted_rows}; "
                          f"po.received events: {result.inserted_events}")
        for reason in result.match_refusals:
            self.stdout.write(f"MATCH REFUSED (nothing posted; listed in /reports/po-exceptions/): {reason}")
