"""Founder-authorised two-line SAMPLE cash seed and one-step reversal."""
from datetime import date, datetime, time
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from acct.models import Account, JournalEntry, JournalLine
from core.models import DatasetKind, DatasetSettings

SOURCE_REF = "SAMPLE_SEED_2026-09-20"
MEMO = "SAMPLE DATA - NOT ACTUALS. Development seed per founder ruling 2026-09-20 (Q-14)."


class Command(BaseCommand):
    help = "Create a two-line SAMPLE cash seed; --reverse reverses it in one step."

    def add_arguments(self, parser):
        parser.add_argument("amount_twd", nargs="?", type=Decimal)
        parser.add_argument("--date", dest="entry_date", type=date.fromisoformat)
        parser.add_argument("--reverse", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        settings = DatasetSettings.load()
        if settings.dataset_kind != DatasetKind.SAMPLE:
            raise CommandError("seed is restricted to SAMPLE mode")
        if options["reverse"]:
            original = JournalEntry.objects.filter(source_ref=SOURCE_REF, source_kind="seed").first()
            if original is None or JournalEntry.objects.filter(reverses=original).exists():
                raise CommandError("seed missing or already reversed")
            when = options["entry_date"] or timezone.localdate()
            at = timezone.make_aware(datetime.combine(when, time.min))
            reversal = JournalEntry.objects.create(occurred_at=at, period=when.strftime("%Y-%m"),
                dataset_kind=DatasetKind.SAMPLE, source_kind="seed", source_ref=SOURCE_REF+":reversal",
                reverses=original, memo="One-step reversal of SAMPLE cash seed")
            for old in original.lines.all():
                JournalLine.objects.create(entry=reversal, account=old.account,
                    debit=old.credit, credit=old.debit, memo=MEMO)
            settings.seed_journal_entry_ref = ""
            settings.save(update_fields=["seed_journal_entry_ref", "updated_at"])
            self.stdout.write(f"seed reversed as entry {reversal.pk}")
            return
        amount = options["amount_twd"]
        if amount is None or amount <= 0 or amount != amount.to_integral_value():
            raise CommandError("a positive integer TWD amount is required")
        if options["entry_date"] is None:
            raise CommandError("--date YYYY-MM-DD is required")
        if JournalEntry.objects.filter(source_ref=SOURCE_REF).exists():
            raise CommandError("seed already exists; reverse it before replacing")
        when = options["entry_date"]
        at = timezone.make_aware(datetime.combine(when, time.min))
        entry = JournalEntry.objects.create(occurred_at=at, period=when.strftime("%Y-%m"),
            dataset_kind=DatasetKind.SAMPLE, source_kind="seed", source_ref=SOURCE_REF, memo=MEMO)
        JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="1121"), debit=amount, memo=MEMO)
        JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="3111"), credit=amount, memo=MEMO)
        settings.seed_journal_entry_ref = SOURCE_REF
        settings.save(update_fields=["seed_journal_entry_ref", "updated_at"])
        self.stdout.write(f"SAMPLE seed recorded as entry {entry.pk}")
