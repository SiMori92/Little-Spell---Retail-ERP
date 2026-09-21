"""Flip the dataset from SAMPLE to ACTUAL.

DATA_REVIEW addendum §A1.4: flipping to ACTUAL requires reversing the seed JE and
posting a founder-signed real opening entry. Nothing else clears it.

This is a STUB in Slice 0, and it is a stub that refuses. The journal tables it must
reverse and post into do not exist until Slice B, so `_real_opening_entry_exists()`
returns False and the command always declines. That is the intended Slice 0
behaviour: a command that flipped the flag without a real opening entry would be
exactly the plugged figure the accounting gate exists to prevent.

The eventual opening entry is TWO LINES ONLY:

    Dr  1121  Cash               <amount>
    Cr  3111  Owner capital      <amount>

The amount is a REQUIRED ARGUMENT. It is never defaulted, inferred, derived from the
seed, or balanced by a plug. There is no suspense account and no rounding account
(SCHEMA_RULINGS 1). If the two sides do not agree, the command fails; it does not
reconcile them.
"""

from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import DatasetKind, DatasetSettings

# SCHEMA_RULINGS 1: money is exact decimal, numeric(18,4). Never a float.
MONEY_EXPONENT = Decimal("0.0001")


def _real_opening_entry_exists() -> bool:
    """True once a founder-signed real opening entry is posted.

    Slice 0 has no journal tables, so this is False by construction. Slice B
    replaces the body with a query against acct_journalentry for a posted,
    non-seed opening entry — and must not weaken the refusal while doing so.
    """
    return False


def _seed_entry_ref(settings_row: DatasetSettings) -> str:
    return settings_row.seed_journal_entry_ref


class Command(BaseCommand):
    help = (
        "Reverse the sample seed journal entry, post the real opening entry "
        "(Dr 1121 Cash / Cr 3111 Owner capital) and flip dataset_kind to ACTUAL. "
        "Refuses while no real opening entry exists."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--amount",
            required=True,
            help=(
                "Opening entry amount in TWD, exact decimal, e.g. 150000.0000. "
                "Required. Never defaulted — a defaulted opening balance is a plugged figure."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen and change nothing.",
        )

    def handle(self, *args, **options):
        amount = self._parse_amount(options["amount"])
        dry_run = options["dry_run"]

        settings_row = DatasetSettings.load()

        if settings_row.dataset_kind == DatasetKind.ACTUAL:
            raise CommandError("dataset_kind is already ACTUAL. Nothing to do.")

        self.stdout.write(f"dataset_kind          : {settings_row.dataset_kind}")
        self.stdout.write(f"seed JE source_ref    : {_seed_entry_ref(settings_row) or '(none recorded)'}")
        self.stdout.write(f"opening entry amount  : {amount} TWD")
        self.stdout.write("opening entry lines   : Dr 1121 Cash / Cr 3111 Owner capital")

        if not _real_opening_entry_exists():
            raise CommandError(
                "REFUSED: no real opening entry exists.\n"
                "\n"
                "dataset_kind stays SAMPLE and the banner stays up.\n"
                "\n"
                "Flipping to ACTUAL requires, per DATA_REVIEW addendum §A1.4:\n"
                "  1. the sample seed JE reversed as one identified entry, and\n"
                "  2. a founder-signed real opening entry posted --\n"
                "     Dr 1121 Cash / Cr 3111 Owner capital, equal amounts.\n"
                "\n"
                "Neither is possible yet: the journal tables are a SLICE B deliverable and\n"
                "this command is a Slice 0 stub. It will not plug a figure to get past this."
            )

        if dry_run:
            self.stdout.write(self.style.WARNING("--dry-run: nothing written."))
            return

        # Slice B fills this in: reverse the seed JE, post the real opening entry and
        # flip the flag, all inside this one transaction. Partial completion here would
        # leave books that claim to be actuals while still carrying the seed.
        with transaction.atomic():
            settings_row.dataset_kind = DatasetKind.ACTUAL
            settings_row.seed_journal_entry_ref = ""
            settings_row.flipped_to_actual_at = timezone.now()
            settings_row.save()
        self.stdout.write(self.style.SUCCESS("dataset_kind is now ACTUAL. The banner is gone."))

    @staticmethod
    def _parse_amount(raw: str) -> Decimal:
        try:
            amount = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            raise CommandError(f"--amount {raw!r} is not an exact decimal.")
        if not amount.is_finite():
            raise CommandError("--amount must be a finite decimal.")
        if amount <= 0:
            raise CommandError("--amount must be greater than zero.")
        if amount != amount.quantize(MONEY_EXPONENT):
            raise CommandError("--amount carries more than 4 decimal places (numeric(18,4)).")
        return amount.quantize(MONEY_EXPONENT)
