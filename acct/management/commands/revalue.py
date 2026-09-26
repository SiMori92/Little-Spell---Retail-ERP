"""Record a non-inventory account revaluation for separate posting."""

from django.core.management.base import CommandError

from acct.management.commands._manual_entry import ManualEntryCommand, positive_amount, required_text


class Command(ManualEntryCommand):
    help = "Create an unposted period.revalued manual entry."
    event_type = "period.revalued"

    def add_entry_arguments(self, parser):
        parser.add_argument("--account", required=True)
        parser.add_argument("--amount", required=True)
        parser.add_argument("--direction", required=True, choices=("gain", "loss"))
        parser.add_argument("--rate-source", required=True)

    def entry_fields(self, options):
        account = required_text(options["account"], "account")
        if account in ("1231", "1232", "1233"):
            raise CommandError("inventory accounts 1231, 1232, 1233 cannot be revalued")
        return {
            "amount": positive_amount(options["amount"]),
            "payload": {
                "revalued_account": account,
                "direction": options["direction"],
                "rate_source": required_text(options["rate_source"], "rate-source"),
            },
        }
