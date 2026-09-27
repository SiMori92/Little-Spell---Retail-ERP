from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from acct.models import JournalLine
from core.models import DatasetKind, DatasetSettings
from ops.models import IgDeal, Product, PurchaseOrder, Supplier
from ops.reporting import ig_pipeline, landed_cost, open_pos, repeat_rate
from ops.intake import ImportRefused, classify_filename
from ops.file_intake import manifest
from ops.receiving import _grn_manifest, _inv_manifest
from ops.payments import _payment_manifest
from ops.etsy_import import etsy_manifest

D = Decimal


class EveryImporterFilenameBoundaryTests(SimpleTestCase):
    def test_all_eleven_kinds_refuse_the_opposite_dataset_filename(self):
        cases = (
            (manifest("receipts"), "SAMPLE_receipts_2026-09.csv", "receipts_2026-09.csv"),
            (manifest("counts"), "SAMPLE_count_2026-09-27.csv", "count_2026-09-27.csv"),
            (manifest("suppliers"), "SAMPLE_suppliers_2026-09-27.csv", "suppliers_2026-09-27.csv"),
            (manifest("products"), "SAMPLE_products_2026-09-27.csv", "products_2026-09-27.csv"),
            (manifest("ig_deals"), "SAMPLE_ig_deals_2026-10.csv", "ig_deals_2026-10.csv"),
            (manifest("po"), "SAMPLE_po_PO-2026-001.csv", "po_PO-2026-001.csv"),
            (_grn_manifest(), "SAMPLE_grn_PO-2026-001_R1.csv", "grn_PO-2026-001_R1.csv"),
            (_inv_manifest(), "SAMPLE_inv_INV-001.csv", "inv_INV-001.csv"),
            (_payment_manifest(), "SAMPLE_pay_PAY-001.csv", "pay_PAY-001.csv"),
            (etsy_manifest("orderitems"), "SAMPLE_etsy_orderitems_2026-09.csv", "etsy_orderitems_2026-09.csv"),
            (etsy_manifest("statement"), "SAMPLE_etsy_statement_2026-09.csv", "etsy_statement_2026-09.csv"),
        )
        self.assertEqual(len(cases), 11)
        for source, sample, actual in cases:
            with self.subTest(kind=source.kind, direction="sample-to-actual"):
                with self.assertRaisesRegex(ImportRefused, "SAMPLE.*ACTUAL"):
                    classify_filename(Path(sample), "ACTUAL", source)
            with self.subTest(kind=source.kind, direction="actual-to-sample"):
                with self.assertRaisesRegex(ImportRefused, "ACTUAL.*SAMPLE"):
                    classify_filename(Path(actual), "SAMPLE", source)


class CombinedUatPackTests(TestCase):
    def test_default_run_validates_every_step_and_rolls_back(self):
        out = StringIO()
        call_command("load_uat_sample", stdout=out)
        self.assertIn("Instagram deals:", out.getvalue())
        self.assertIn("transaction rolled back", out.getvalue())
        self.assertFalse(Supplier.objects.exists())

    def test_actual_mode_refuses_the_sample_pack(self):
        row = DatasetSettings.load()
        row.dataset_kind = DatasetKind.ACTUAL
        row.save()
        with self.assertRaisesRegex(CommandError, "restricted to SAMPLE"):
            call_command("load_uat_sample", "--commit", stdout=StringIO())

    def test_combined_pack_rederives_run_a_and_b_figures(self):
        call_command("load_uat_sample", "--commit", stdout=StringIO())
        self.assertEqual((Supplier.objects.count(), Product.objects.count(),
                          PurchaseOrder.objects.count(), IgDeal.objects.count()), (3, 12, 4, 13))

        # At the combined pack's final state PO-002 is closed and PO-003 received;
        # PO-001 remains draft and the uninvoiced PO-004 remains committed.
        report = open_pos("2026-03-31")
        committed = report.sections[0].rows[-1]
        drafts = report.sections[1].rows[-1]
        self.assertEqual((committed["pieces"].amount, committed["committed"].amount),
                         (D("10000"), D("18000.0000")))
        self.assertEqual((drafts["pieces"].amount, drafts["committed"].amount),
                         (D("14000"), D("231000.0000")))

        costs = {(row["po"], row["sku"]): row for row in landed_cost("2026-03-31").rows}
        self.assertEqual(costs[("PO-2026-003", "PKG-MAIL-LS")]["per_piece"].amount, D("7.0000"))
        card = costs[("PO-2026-003", "PKG-CARD-LS")]
        self.assertEqual((card["per_piece"].amount, card["to_stock"].amount,
                          card["to_5121"].amount),
                         (D("1.9425"), D("38461.5000"), D("388.5000")))

        balances = {code: sum((line.debit - line.credit for line in JournalLine.objects.filter(
            account_id=code)), D(0)) for code in ("1121", "1266", "2171")}
        self.assertEqual(balances, {"1121": D("-135450.0000"), "1266": D("0.0000"),
                                    "2171": D("-143850.0000")})

        pipeline = ig_pipeline("2026-11-15")
        self.assertEqual([(row["deal_id"], row["days"].amount)
                          for row in pipeline.sections[0].rows],
                         [("IG-202610-001", D(41)), ("IG-202610-002", D(36)),
                          ("IG-202610-012", D(31))])
        oct_row = next(row for row in pipeline.sections[2].rows if row["month"] == "2026-10")
        self.assertEqual((oct_row["enquiries"].amount, oct_row["quoted"].amount,
                          oct_row["paid"].amount, oct_row["quote_rate"].amount,
                          oct_row["paid_rate"].amount),
                         (D(12), D(10), D(6), D("83.3333"), D("50.0000")))
        repeat = repeat_rate("2026-10").rows[0]
        self.assertEqual((repeat["customers"].amount, repeat["repeat_customers"].amount,
                          repeat["rate"].amount), (D(4), D(2), D(50)))
