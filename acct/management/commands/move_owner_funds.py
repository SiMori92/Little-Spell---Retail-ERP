"""Record owner funding, drawings or loans for separate posting."""

from acct.management.commands._manual_entry import ManualEntryCommand, positive_amount


class Command(ManualEntryCommand):
    help = "Create an unposted owner.funds_moved manual entry."
    event_type = "owner.funds_moved"

    def add_entry_arguments(self, parser):
        parser.add_argument("--amount", required=True)
        parser.add_argument("--funds-type", required=True, choices=("capital", "drawings", "loan"))

    def entry_fields(self, options):
        return {"amount": positive_amount(options["amount"]), "payload": {"funds_type": options["funds_type"]}}
