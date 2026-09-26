"""Record a tax assessment awaiting professional confirmation."""

from acct.management.commands._manual_entry import ManualEntryCommand, positive_amount


class Command(ManualEntryCommand):
    help = "Create an unposted tax.assessed entry flagged for professional confirmation."
    event_type = "tax.assessed"

    def add_entry_arguments(self, parser):
        parser.add_argument("--amount", required=True)

    def entry_fields(self, options):
        return {"amount": positive_amount(options["amount"]), "needs_prof_conf": True}
