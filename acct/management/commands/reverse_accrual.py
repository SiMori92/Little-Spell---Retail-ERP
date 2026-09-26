"""Reverse one posted accrual for separate posting."""

from django.core.management.base import CommandError

from acct.management.commands._manual_entry import ManualEntryCommand
from acct.models import AcctManualEntry


class Command(ManualEntryCommand):
    help = "Create an unposted reversal of a posted period.accrued entry."
    event_type = "period.accrual_reversed"

    def add_entry_arguments(self, parser):
        parser.add_argument("--reverses", required=True, type=int)

    def entry_fields(self, options):
        original = AcctManualEntry.objects.select_for_update().filter(pk=options["reverses"]).first()
        if original is None or original.event_type != "period.accrued" or not original.posted_entry_id:
            raise CommandError("--reverses needs a posted period.accrued manual entry")
        return {"amount": original.amount, "reverses": original}
