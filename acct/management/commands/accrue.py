"""Record an estimated expense accrual for separate posting."""

from django.core.management.base import CommandError

from acct.management.commands._manual_entry import ManualEntryCommand, positive_amount, required_text


class Command(ManualEntryCommand):
    help = "Create an unposted period.accrued manual entry."
    event_type = "period.accrued"

    def add_entry_arguments(self, parser):
        parser.add_argument("--expense-account", required=True)
        parser.add_argument("--accrual-account", required=True)
        parser.add_argument("--amount", required=True)
        parser.add_argument("--basis-note", required=True)

    def entry_fields(self, options):
        accrual = required_text(options["accrual_account"], "accrual-account")
        if accrual not in ("2191", "2193", "2197"):
            raise CommandError("--accrual-account must be one of 2191, 2193, 2197")
        return {
            "amount": positive_amount(options["amount"]),
            "basis": "estimate",
            "payload": {
                "expense_account": required_text(options["expense_account"], "expense-account"),
                "accrual_account": accrual,
                "basis_note": required_text(options["basis_note"], "basis-note"),
            },
        }
