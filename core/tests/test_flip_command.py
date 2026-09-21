"""The flip-to-ACTUAL command must REFUSE while no real opening entry exists.

DATA_REVIEW addendum §A1.4. In Slice 0 there are no journal tables, so it refuses
unconditionally — and that refusal is the deliverable, not a limitation to work
around.
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import DatasetKind, DatasetSettings


class FlipCommandRefusesTests(TestCase):
    def test_it_refuses_while_no_real_opening_entry_exists(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("flip_dataset_to_actual", "--amount", "150000", stdout=StringIO())
        self.assertIn("REFUSED", str(ctx.exception))

    def test_a_refused_flip_leaves_the_flag_on_sample(self):
        with self.assertRaises(CommandError):
            call_command("flip_dataset_to_actual", "--amount", "150000", stdout=StringIO())
        self.assertEqual(DatasetSettings.load().dataset_kind, DatasetKind.SAMPLE)

    def test_the_banner_survives_a_refused_flip(self):
        with self.assertRaises(CommandError):
            call_command("flip_dataset_to_actual", "--amount", "150000", stdout=StringIO())
        self.assertIn("SAMPLE DATA — NOT ACTUALS", self.client.get("/").content.decode())


class AmountIsRequiredAndExactTests(TestCase):
    """No plugged figures, under any label. The amount is supplied, never invented."""

    def test_amount_is_a_required_argument(self):
        with self.assertRaises(CommandError):
            call_command("flip_dataset_to_actual", stdout=StringIO())

    def test_a_non_numeric_amount_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("flip_dataset_to_actual", "--amount", "about-150k", stdout=StringIO())

    def test_zero_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("flip_dataset_to_actual", "--amount", "0", stdout=StringIO())

    def test_a_negative_amount_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("flip_dataset_to_actual", "--amount", "-150000", stdout=StringIO())

    def test_more_than_four_decimal_places_is_rejected(self):
        """SCHEMA_RULINGS 1: numeric(18,4). Silently rounding here would be a plug."""
        with self.assertRaises(CommandError) as ctx:
            call_command("flip_dataset_to_actual", "--amount", "150000.123456", stdout=StringIO())
        self.assertIn("4 decimal places", str(ctx.exception))

    def test_the_parsed_amount_is_an_exact_decimal_never_a_float(self):
        from decimal import Decimal

        from core.management.commands.flip_dataset_to_actual import Command

        parsed = Command._parse_amount("150000.10")
        self.assertIsInstance(parsed, Decimal)
        self.assertEqual(parsed, Decimal("150000.1000"))


class DryRunTests(TestCase):
    def test_dry_run_still_refuses_rather_than_reporting_a_would_be_success(self):
        with self.assertRaises(CommandError):
            call_command(
                "flip_dataset_to_actual", "--amount", "150000", "--dry-run", stdout=StringIO()
            )
