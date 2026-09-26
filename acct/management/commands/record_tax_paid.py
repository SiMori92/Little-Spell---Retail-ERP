"""Record a tax payment for separate posting."""

from acct.management.commands._manual_entry import ManualEntryCommand, positive_amount


class Command(ManualEntryCommand):
    help = "Create an unposted tax.paid manual entry."
    event_type = "tax.paid"

    def add_entry_arguments(self, parser):
        parser.add_argument("--amount", required=True)

    def entry_fields(self, options):
        return {"amount": positive_amount(options["amount"])}
