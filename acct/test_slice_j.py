"""Slice J tests assert on IDs, counts and codes; never render customer rows."""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from acct.models import AcctManualEntry, JournalLine, Period


class ManualEntryCommandTests(TestCase):
    common = ("--actor", "synthetic-operator", "--period", "2025-03", "--occurred-on", "2025-03-27")
    extras = {
        "accrue": ("--expense-account", "6131", "--accrual-account", "2191", "--amount", "10", "--basis-note", "synthetic estimate"),
        "reverse_accrual": (),
        "revalue": ("--account", "1191", "--amount", "10", "--direction", "loss", "--rate-source", "synthetic rate"),
        "record_tax_assessed": ("--amount", "10"),
        "record_tax_paid": ("--amount", "10"),
        "move_owner_funds": ("--amount", "10", "--funds-type", "capital"),
    }

    def run_entry(self, name, *, evidence=None, extras=None, common=None):
        args = list(self.common if common is None else common)
        args += ["--evidence-ref", evidence or f"synthetic-{name}"]
        args += list(self.extras[name] if extras is None else extras)
        out = StringIO()
        call_command(name, *args, stdout=out)
        return out.getvalue(), AcctManualEntry.objects.latest("id")

    def posted_accrual(self):
        _, original = self.run_entry("accrue")
        call_command("post_accounting_event", "manual", str(original.pk), stdout=StringIO())
        original.refresh_from_db()
        return original

    def reverse_extras(self, original):
        return ("--reverses", str(original.pk))

    def test_each_command_creates_one_unposted_row_that_posts_cleanly(self):
        original = self.posted_accrual()
        cases = ("reverse_accrual", "revalue", "record_tax_assessed", "record_tax_paid", "move_owner_funds")
        for name in cases:
            with self.subTest(command=name):
                extra = self.reverse_extras(original) if name == "reverse_accrual" else None
                output, row = self.run_entry(name, extras=extra)
                self.assertIn(f"created unposted manual entry {row.pk}", output)
                self.assertIsNone(row.posted_entry_id)
                call_command("post_accounting_event", "manual", str(row.pk), stdout=StringIO())
                row.refresh_from_db()
                self.assertIsNotNone(row.posted_entry_id)
                lines = JournalLine.objects.filter(entry_id=row.posted_entry_id)
                self.assertEqual(lines.count(), 2)
                self.assertEqual(sum(line.debit - line.credit for line in lines), 0)
        self.assertIsNotNone(original.posted_entry_id)

    def test_all_six_require_actor_and_evidence_before_database_access(self):
        original = self.posted_accrual()
        for name in self.extras:
            extra = self.reverse_extras(original) if name == "reverse_accrual" else self.extras[name]
            for missing in ("--actor", "--evidence-ref"):
                with self.subTest(command=name, missing=missing):
                    args = list(self.common) + ["--evidence-ref", f"synthetic-missing-{name}"] + list(extra)
                    index = args.index(missing)
                    del args[index:index + 2]
                    before = AcctManualEntry.objects.count()
                    with self.assertRaises(CommandError):
                        call_command(name, *args, stdout=StringIO())
                    self.assertEqual(AcctManualEntry.objects.count(), before)

    def test_identical_rerun_reports_existing_and_conflicting_details_refuse(self):
        output, row = self.run_entry("record_tax_paid")
        self.assertIn("created unposted", output)
        before = AcctManualEntry.objects.count()
        output, same = self.run_entry("record_tax_paid")
        self.assertEqual(same.pk, row.pk)
        self.assertIn(f"existing unposted manual entry {row.pk}", output)
        self.assertEqual(AcctManualEntry.objects.count(), before)
        with self.assertRaisesRegex(CommandError, "natural key already exists"):
            self.run_entry("record_tax_paid", extras=("--amount", "11"))

    def test_accrual_input_refusals(self):
        without_basis = self.extras["accrue"][:-2]
        with self.assertRaises(CommandError):
            self.run_entry("accrue", extras=without_basis)
        self.assertEqual(AcctManualEntry.objects.count(), 0)
        wrong_account = list(self.extras["accrue"])
        wrong_account[wrong_account.index("--accrual-account") + 1] = "2211"
        with self.assertRaisesRegex(CommandError, "2191, 2193, 2197"):
            self.run_entry("accrue", extras=wrong_account)
        self.assertEqual(AcctManualEntry.objects.count(), 0)

    def test_reversal_requires_posted_original_and_refuses_second_reversal(self):
        _, original = self.run_entry("accrue")
        with self.assertRaisesRegex(CommandError, "posted period.accrued"):
            self.run_entry("reverse_accrual", extras=self.reverse_extras(original))
        call_command("post_accounting_event", "manual", str(original.pk), stdout=StringIO())
        _, first = self.run_entry("reverse_accrual", extras=self.reverse_extras(original))
        self.assertEqual(first.amount, original.amount)
        with self.assertRaisesRegex(CommandError, "already reversed"):
            self.run_entry("reverse_accrual", evidence="synthetic-second-reversal", extras=self.reverse_extras(original))
        self.assertEqual(AcctManualEntry.objects.filter(event_type="period.accrual_reversed").count(), 1)
        with self.assertRaises(CommandError):
            self.run_entry("reverse_accrual", extras=("--reverses", str(original.pk), "--amount", "5"))

    def test_revaluation_rejects_inventory_and_tax_flag_is_always_true(self):
        for code in ("1231", "1232", "1233"):
            extra = list(self.extras["revalue"])
            extra[extra.index("--account") + 1] = code
            with self.subTest(account=code), self.assertRaisesRegex(CommandError, "1231, 1232, 1233"):
                self.run_entry("revalue", extras=extra)
        _, assessed = self.run_entry("record_tax_assessed")
        self.assertTrue(assessed.needs_prof_conf)
        with self.assertRaises(CommandError):
            self.run_entry("record_tax_assessed", extras=("--amount", "10", "--needs-prof-conf", "false"))

    def test_all_six_refuse_closed_period(self):
        original = self.posted_accrual()
        Period.objects.create(period="2025-03", status="CLOSED")
        for name in self.extras:
            with self.subTest(command=name), self.assertRaisesRegex(CommandError, "2025-03 is CLOSED"):
                extra = self.reverse_extras(original) if name == "reverse_accrual" else None
                self.run_entry(name, evidence=f"synthetic-closed-{name}", extras=extra)

    def test_all_six_refuse_out_of_period_date(self):
        original = self.posted_accrual()
        common = ("--actor", "synthetic-operator", "--period", "2025-03", "--occurred-on", "2025-04-01")
        for name in self.extras:
            with self.subTest(command=name), self.assertRaisesRegex(CommandError, "inside period 2025-03"):
                extra = self.reverse_extras(original) if name == "reverse_accrual" else None
                self.run_entry(name, evidence=f"synthetic-date-{name}", extras=extra, common=common)

    def test_dry_run_prints_exact_lines_and_writes_no_manual_rows(self):
        original = self.posted_accrual()
        expected = {
            "accrue": ("Dr 6131 10.0000 TWD", "Cr 2191 10.0000 TWD"),
            "reverse_accrual": ("Dr 2191 10.0000 TWD", "Cr 6131 10.0000 TWD"),
            "revalue": ("Dr 7112 10.0000 TWD", "Cr 1191 10.0000 TWD"),
            "record_tax_assessed": ("Dr 6182 10.0000 TWD", "Cr 2194 10.0000 TWD"),
            "record_tax_paid": ("Dr 2194 10.0000 TWD", "Cr 1121 10.0000 TWD"),
            "move_owner_funds": ("Dr 1121 10.0000 TWD", "Cr 3111 10.0000 TWD"),
        }
        for name, journal_lines in expected.items():
            with self.subTest(command=name):
                extra = self.reverse_extras(original) if name == "reverse_accrual" else self.extras[name]
                args = list(self.common) + ["--evidence-ref", f"synthetic-dry-{name}"] + list(extra) + ["--dry-run"]
                before = AcctManualEntry.objects.count()
                out = StringIO()
                call_command(name, *args, stdout=out)
                self.assertEqual(out.getvalue().splitlines(), list(journal_lines))
                self.assertEqual(AcctManualEntry.objects.count(), before)
