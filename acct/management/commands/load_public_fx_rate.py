"""Manual evidence-backed public-rate loader; no unverified web fetch."""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from acct.models import FxRate


class Command(BaseCommand):
    help = "Record a transaction-date public TWD rate with evidence from Bank of Taiwan."

    def add_arguments(self, parser):
        parser.add_argument("rate_date", type=date.fromisoformat)
        parser.add_argument("currency")
        parser.add_argument("rate", type=Decimal)
        parser.add_argument("--evidence-ref", required=True)

    def handle(self, *args, **options):
        rate = options["rate"]
        if rate <= 0 or len(options["currency"]) != 3:
            raise CommandError("positive rate and three-letter currency required")
        obj, created = FxRate.objects.get_or_create(
            rate_date=options["rate_date"], currency=options["currency"].upper(),
            kind="public", source_event_key="",
            defaults={"rate": rate, "rate_source": "manual", "evidence_ref": options["evidence_ref"]},
        )
        if not created and (obj.rate != rate or obj.evidence_ref != options["evidence_ref"]):
            raise CommandError("existing public rate differs; investigate source before correction")
        self.stdout.write(f"public rate {'created' if created else 'already recorded'} for {obj.currency} {obj.rate_date}")
