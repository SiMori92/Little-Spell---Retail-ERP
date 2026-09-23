"""Explicit, dry-run-first Etsy importer. Output contains IDs/counts, never rows."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ops.etsy_import import ImportRefused, import_etsy, load_coupon_funding


class Command(BaseCommand):
    help = "Validate a pair of Etsy exports; --commit is refused while schema fixtures are unverified."

    def add_arguments(self, parser):
        parser.add_argument("--orders", type=Path, required=True)
        parser.add_argument("--statement", type=Path, required=True)
        parser.add_argument("--coupon-funding", type=Path)
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        coupon_path = options["coupon_funding"] or Path(__file__).resolve().parents[4] / "state" / "coupon_funding.csv"
        try:
            mapping = load_coupon_funding(coupon_path) if coupon_path.exists() else None
            if options["coupon_funding"] and mapping is None:
                raise ImportRefused(f"Founder coupon-funding file is absent: {coupon_path.name}")
            result = import_etsy(options["orders"], options["statement"],
                                 commit=options["commit"], coupon_funding=mapping)
        except (ImportRefused, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Order rows parsed: {result.parsed_order_rows}; statement rows parsed: {result.parsed_statement_rows}; "
            f"rows inserted: {result.inserted_rows}; events emitted: {result.inserted_events}"
        )
        for item in result.reconciling_items:
            self.stdout.write(f"RECONCILING: {item}")
        for item in result.blockers:
            self.stdout.write(f"BLOCKER: {item}")
        self.stdout.write("Assumed export timezone: Asia/Taipei; source files contain dates without times or zones.")
