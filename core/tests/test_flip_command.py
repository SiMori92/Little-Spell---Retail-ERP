import hashlib
import csv
from datetime import datetime
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, TransactionTestCase

from acct.models import AcctManualEntry, CloseRun, JournalEntry, JournalLine
from acct.posting import PostingError, post_event
from core.models import DatasetKind, DatasetSettings, SecretRotation
from ops.file_intake import import_counts, import_po, import_products, import_suppliers
from ops.models import LedgerEvent, Product, PurchaseOrder, Supplier


ARGS = ("--amount", "150000.0000", "--funding-type", "capital",
        "--actor", "founder", "--evidence-ref", "LIVE-OPEN-001")


def record_rotation(secret=None):
    return SecretRotation.objects.create(
        actor="founder", evidence_ref="ROTATE-001",
        secret_key_sha256=hashlib.sha256((secret or settings.SECRET_KEY).encode()).hexdigest(),
        db_password_rotated=True,
    )


class FlipCommandTests(TestCase):
    def test_missing_rotation_is_named_and_writes_nothing(self):
        with self.assertRaisesRegex(CommandError, "no SecretRotation row exists"):
            call_command("flip_dataset_to_actual", *ARGS, stdout=StringIO())
        self.assertEqual(DatasetSettings.load().dataset_kind, DatasetKind.SAMPLE)
        self.assertFalse(AcctManualEntry.objects.exists())

    def test_mismatched_latest_rotation_is_named(self):
        record_rotation("some-other-secret")
        with self.assertRaisesRegex(CommandError, "does not match the running SECRET_KEY"):
            call_command("flip_dataset_to_actual", *ARGS, stdout=StringIO())

    def test_any_sample_dataset_table_is_named(self):
        record_rotation()
        CloseRun.objects.create(period="2026-09", dataset_kind="SAMPLE", runner="test",
            started_at="2026-09-01T00:00:00Z", finished_at="2026-09-01T00:00:01Z",
            elapsed_seconds=1, status="PASS", gate_results=[], remaining_open=[], signature="x")
        with self.assertRaisesRegex(CommandError, "acct_closerun"):
            call_command("flip_dataset_to_actual", *ARGS, stdout=StringIO())

    def test_success_posts_exactly_two_actual_lines_and_flips(self):
        record_rotation()
        out = StringIO()
        call_command("flip_dataset_to_actual", *ARGS, stdout=out)
        row = DatasetSettings.load()
        self.assertEqual(row.dataset_kind, DatasetKind.ACTUAL)
        self.assertIsNotNone(row.flipped_to_actual_at)
        event = AcctManualEntry.objects.get()
        self.assertEqual(event.payload, {"funds_type": "capital"})
        entry = JournalEntry.objects.get(pk=event.posted_entry_id)
        self.assertEqual(entry.dataset_kind, DatasetKind.ACTUAL)
        self.assertEqual(
            list(entry.lines.order_by("id").values_list("account_id", "debit", "credit")),
            [("1121", 150000, 0), ("3111", 0, 150000)],
        )

    def test_loan_uses_2281(self):
        record_rotation()
        args = tuple("loan" if value == "capital" else value for value in ARGS)
        call_command("flip_dataset_to_actual", *args, stdout=StringIO())
        self.assertEqual(set(JournalLine.objects.values_list("account_id", flat=True)), {"1121", "2281"})

    def test_second_run_refuses_already_actual(self):
        record_rotation()
        call_command("flip_dataset_to_actual", *ARGS, stdout=StringIO())
        with self.assertRaisesRegex(CommandError, "already ACTUAL"):
            call_command("flip_dataset_to_actual", *ARGS, stdout=StringIO())

    def test_failure_after_post_rolls_back_everything(self):
        record_rotation()
        real_save = DatasetSettings.save

        def fail_on_flip(instance, *args, **kwargs):
            if instance.dataset_kind == DatasetKind.ACTUAL:
                raise RuntimeError("forced after-entry failure")
            return real_save(instance, *args, **kwargs)

        with patch.object(DatasetSettings, "save", fail_on_flip):
            with self.assertRaisesRegex(RuntimeError, "forced after-entry failure"):
                call_command("flip_dataset_to_actual", *ARGS, stdout=StringIO())
        self.assertEqual(DatasetSettings.load().dataset_kind, DatasetKind.SAMPLE)
        self.assertFalse(AcctManualEntry.objects.exists())
        self.assertFalse(JournalEntry.objects.exists())

    def test_dry_run_prints_every_check_and_lines_without_writing(self):
        record_rotation()
        out = StringIO()
        call_command("flip_dataset_to_actual", *ARGS, "--dry-run", stdout=out)
        text = out.getvalue()
        self.assertEqual(text.count("PASS:"), 8)
        self.assertIn("Dr 1121 150000.0000 TWD", text)
        self.assertIn("Cr 3111 150000.0000 TWD", text)
        self.assertIn("nothing written", text)
        self.assertFalse(AcctManualEntry.objects.exists())

    def test_amount_must_be_positive_and_exact(self):
        for bad in ("0", "-1", "1.00001", "not-money"):
            args = list(ARGS)
            args[1] = bad
            with self.subTest(bad=bad), self.assertRaises(CommandError):
                call_command("flip_dataset_to_actual", *args, stdout=StringIO())

    def test_funding_actor_and_evidence_are_mandatory(self):
        cases = [("--funding-type", "gift"), ("--actor", " "), ("--evidence-ref", " ")]
        for option, value in cases:
            args = list(ARGS)
            args[args.index(option) + 1] = value
            with self.subTest(option=option), self.assertRaises(CommandError):
                call_command("flip_dataset_to_actual", *args, stdout=StringIO())

    def test_seed_sample_cash_refuses_after_actual(self):
        row = DatasetSettings.load()
        row.dataset_kind = DatasetKind.ACTUAL
        row.save()
        with self.assertRaisesRegex(CommandError, "restricted to SAMPLE"):
            call_command("seed_sample_cash", "100", "--date", "2026-09-27", stdout=StringIO())


class OneWayDatabaseGuardTests(TransactionTestCase):
    def test_model_refuses_actual_back_to_sample(self):
        row = DatasetSettings.load()
        row.dataset_kind = DatasetKind.ACTUAL
        row.save()
        row.dataset_kind = DatasetKind.SAMPLE
        with self.assertRaisesRegex(RuntimeError, "one-way"):
            row.save()


class EmptyActualDatabaseFirstPoTests(TestCase):
    def write_csv(self, directory, name, header, rows):
        path = Path(directory) / name
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def test_flip_then_actual_master_data_opening_count_and_first_po(self):
        record_rotation()
        call_command("flip_dataset_to_actual", *ARGS, stdout=StringIO())
        with TemporaryDirectory() as directory:
            supplier = self.write_csv(directory, "suppliers_2026-09-27.csv",
                ["supplier_ref", "legal_name", "country", "currency", "default_incoterm",
                 "payment_terms", "can_invoice_to_tax_id", "declaration_ref", "evidence_ref"],
                [["SUP-001", "Actual printer", "TW", "TWD", "EXW", "Net 30", "yes",
                  "compliance/suppliers/SUP-001.pdf", "supplier-onboarding-001"]])
            products = self.write_csv(directory, "products_2026-09-27.csv",
                ["sku", "name", "pieces_per_sale_unit", "supplier_ref", "ingredient_ref",
                 "evidence_ref", "product_type"],
                [["TS-FL-001-S", "Actual sticker", "1", "SUP-001",
                  "compliance/suppliers/TS-FL-001-S.pdf", "product-onboarding-001", "sellable"]])
            count = self.write_csv(directory, "count_2026-09-27.csv",
                ["counted_at", "evidence_ref", "sku", "qty_pieces", "agreed_unit_cost_twd", "condition"],
                [["2026-09-27", "opening-stocktake-001", "TS-FL-001-S", "10", "12.0000", "sellable"]])
            po = self.write_csv(directory, "po_PO-2026-001.csv",
                ["po_number", "supplier_ref", "po_date", "target_delivery_date", "currency",
                 "payment_terms", "incoterm", "quote_ref", "status", "line_no", "sku", "qty_pieces",
                 "unit_price_twd", "setup_charge_twd", "line_total_twd", "min_order_qty_pieces",
                 "artwork_ref", "evidence_ref"],
                [["PO-2026-001", "SUP-001", "2026-09-27", "2026-10-15", "TWD", "Net 30", "EXW",
                  "QUOTE-001", "sent", "1", "TS-FL-001-S", "100", "10.0000", "0.0000",
                  "1000.0000", "100", "", "po-001"]])

            import_suppliers(supplier, commit=True)
            import_products(products, commit=True)
            imported = import_counts(count, commit=True)
            self.assertEqual(imported.inserted_events, 1)
            opening = LedgerEvent.objects.get(event_type="inventory.opening_counted")
            post_event(opening)
            second = LedgerEvent(
                event_type="inventory.opening_counted", entity_table="ops.stockcount", entity_id=999,
                occurred_at=datetime(2026, 9, 28, 12, tzinfo=ZoneInfo("Asia/Taipei")),
                idempotency_key="second-opening", payload=opening.payload,
                source_filename="count_2026-09-28.csv", dataset_kind="ACTUAL")
            with self.assertRaisesRegex(PostingError, "opening count fires once per dataset"):
                post_event(second)
            import_po(po, commit=True)

        actual_supplier = Supplier.objects.get(supplier_ref="SUP-001")
        self.assertEqual(actual_supplier.dataset_kind, "ACTUAL")
        self.assertEqual(Product.objects.get().supplier, actual_supplier)
        self.assertEqual(PurchaseOrder.objects.get().status, "sent")
