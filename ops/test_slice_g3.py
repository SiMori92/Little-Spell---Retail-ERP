"""Slice G-3: supplier deposits, receipt application, balances, refunds and forfeits."""

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from django.test import TestCase

from acct.gates import g2
from acct.models import JournalEntry, JournalLine
from acct.posting import PostingError, plan
from core.models import DatasetSettings
from ops.file_intake import import_po, import_products, import_suppliers, load_schema
from ops.intake import ImportRefused
from ops.models import LedgerEvent, PurchaseOrder, SupplierInvoice, SupplierPayment
from ops.payments import deposit_open, import_supplier_payment, invoice_open
from ops.receiving import import_grn, import_invoice, pro_rata_deposit
from ops.reporting import deposit_reconciliation, payables, supplier_deposits

D = Decimal
TZ = ZoneInfo("Asia/Taipei")
SAMPLES = Path(__file__).resolve().parents[1] / "docs" / "samples" / "g3"


class SupplierPaymentBase(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        DatasetSettings.objects.get_or_create(pk=1, defaults={"dataset_kind": "SAMPLE"})
        import_suppliers(SAMPLES / "SAMPLE_suppliers_2026-09-27.csv", commit=True)
        import_products(SAMPLES / "SAMPLE_products_2026-09-27.csv", commit=True)
        import_po(SAMPLES / "SAMPLE_po_PO-2026-002.csv", commit=True)

    def csv(self, filename, header, rows):
        path = Path(self.temp.name) / filename
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def payment(self, ref, kind, amount, *, invoice="", bank="1121", bank_ref="BANK-REF",
                evidence="SAMPLE evidence", paid_on="2026-01-28", commit=True):
        row = {"payment_ref": ref, "paid_on": paid_on, "supplier_ref": "SUP-002",
               "po_number": "PO-2026-002", "invoice_no": invoice, "payment_kind": kind,
               "amount_twd": str(amount), "bank_account": bank, "bank_ref": bank_ref,
               "evidence_ref": evidence}
        return import_supplier_payment(self.csv(f"SAMPLE_pay_{ref}.csv", load_schema("pay")["header"], [row]),
                                       commit=commit)

    def deposit(self):
        return import_supplier_payment(SAMPLES / "SAMPLE_pay_DEP-002.csv", commit=True)

    def receive_a(self, *, stated=None):
        import_grn(SAMPLES / "SAMPLE_grn_PO-2026-002_R1.csv", commit=True)
        if stated is None:
            return import_invoice(SAMPLES / "SAMPLE_inv_INV-A.csv", commit=True)
        rows = list(csv.DictReader((SAMPLES / "SAMPLE_inv_INV-A.csv").open(encoding="utf-8")))
        rows[0]["deposit_applied_twd"] = str(stated)
        return import_invoice(self.csv("SAMPLE_inv_INV-A.csv", load_schema("inv")["header"], rows), commit=True)

    def receive_b(self):
        import_grn(SAMPLES / "SAMPLE_grn_PO-2026-002_R2.csv", commit=True)
        return import_invoice(SAMPLES / "SAMPLE_inv_INV-B.csv", commit=True)

    def cancel_po(self):
        rows = list(csv.DictReader((SAMPLES / "SAMPLE_po_PO-2026-002.csv").open(encoding="utf-8")))
        for row in rows:
            row["status"] = "cancelled"
        import_po(self.csv("SAMPLE_po_PO-2026-002.csv", load_schema("po")["header"], rows), commit=True)

    def add_settlement_source(self):
        entry = JournalEntry.objects.create(occurred_at=datetime(2026, 1, 1, 12, tzinfo=TZ), period="2026-01",
                                            dataset_kind="SAMPLE", source_kind="ops",
                                            source_ref="ops:test-settlement-source", memo_only=True)
        LedgerEvent.objects.create(event_type="settlement.received", entity_table="ops.test", entity_id=1,
                                   occurred_at=datetime(2026, 1, 1, 12, tzinfo=TZ), currency="TWD",
                                   payload={}, idempotency_key="test-settlement-source",
                                   source_filename="SAMPLE synthetic", dataset_kind="SAMPLE",
                                   posted_entry_id=entry.pk)


class PostingAndIntakeRefusalTests(SupplierPaymentBase):
    def candidate(self, payload, currency="TWD"):
        return LedgerEvent(event_type="po.paid", entity_table="ops.supplierpayment", entity_id=1,
                           occurred_at=datetime(2026, 1, 13, 12, tzinfo=TZ), currency=currency,
                           payload=payload, idempotency_key="candidate", source_filename="SAMPLE_pay_X.csv",
                           dataset_kind="SAMPLE")

    def test_i1_missing_unknown_and_exact_posting_rules(self):
        base = {"amount_twd": "10", "po_number": "PO-2026-002", "bank_account": "1121",
                "bank_ref": "B", "evidence_ref": "E"}
        with self.assertRaisesRegex(PostingError, "required payload field payment_kind is missing"):
            plan(self.candidate(base))
        with self.assertRaisesRegex(PostingError, "unknown payment_kind"):
            plan(self.candidate({**base, "payment_kind": "guess"}))
        expected = {"deposit": (("1266", D("10"), D(0)), ("1121", D(0), D("10"))),
                    "balance": (("2171", D("10"), D(0)), ("1121", D(0), D("10"))),
                    "deposit_refund": (("1121", D("10"), D(0)), ("1266", D(0), D("10"))),
                    "deposit_forfeit": (("6199", D("10"), D(0)), ("1266", D(0), D("10")))}
        for kind, wanted in expected.items():
            payload = {**base, "payment_kind": kind, "invoice_no": "INV-A"}
            if kind == "deposit_forfeit":
                payload["bank_ref"] = ""
            lines = plan(self.candidate(payload))
            self.assertEqual(tuple((line.account, line.debit, line.credit) for line in lines), wanted)
        self.assertFalse(any(line.account == "2171" for line in plan(
            self.candidate({**base, "payment_kind": "deposit"}))))

    def test_i2_deposit_status_receipt_and_cap_refusals(self):
        with self.assertRaisesRegex(ImportRefused, "exceed PO value excluding tax"):
            self.payment("TOO-MUCH", "deposit", "129000.0001")
        self.deposit()
        import_grn(SAMPLES / "SAMPLE_grn_PO-2026-002_R1.csv", commit=True)
        with self.assertRaisesRegex(ImportRefused, "refused after a receipt exists"):
            self.payment("LATE-DEP", "deposit", "1")

    def test_i3_balance_needs_posted_invoice_and_overpay_by_point_zero_zero_zero_one_fails(self):
        with self.assertRaisesRegex(ImportRefused, "requires posted supplier invoice INV-A"):
            self.payment("EARLY", "balance", "1", invoice="INV-A")
        self.deposit()
        self.receive_a()
        with self.assertRaisesRegex(ImportRefused, "overpays invoice INV-A"):
            self.payment("OVER", "balance", "43500.0001", invoice="INV-A")

    def test_i6_cancelled_only_open_balance_evidence_and_bank_ref(self):
        self.deposit()
        with self.assertRaisesRegex(ImportRefused, "requires cancelled PO"):
            self.payment("EARLY-REF", "deposit_refund", "1")
        self.cancel_po()
        with self.assertRaisesRegex(ImportRefused, "requires bank_ref"):
            self.payment("NO-BANK", "deposit_refund", "1", bank_ref="")
        with self.assertRaisesRegex(ImportRefused, "deposit_forfeit has no bank_ref"):
            self.payment("BAD-FORFEIT", "deposit_forfeit", "1", bank_ref="B")
        with self.assertRaisesRegex(ImportRefused, "evidence_ref is required"):
            self.payment("NO-EVID", "deposit_forfeit", "1", bank_ref="", evidence="")
        with self.assertRaisesRegex(ImportRefused, "exceeds open 1266"):
            self.payment("OVER-REF", "deposit_refund", "38700.0001")

    def test_i7_twd_1121_only(self):
        with self.assertRaisesRegex(ImportRefused, r"R-2.6"):
            self.payment("WRONG-BANK", "deposit", "1", bank="1122")
        payload = {"amount_twd": "1", "payment_kind": "deposit", "po_number": "PO-2026-002",
                   "bank_account": "1121", "bank_ref": "B", "evidence_ref": "E"}
        with self.assertRaisesRegex(PostingError, r"R-2.6"):
            plan(self.candidate(payload, currency="USD"))

    def test_i9_idempotency_pii_and_required_provenance(self):
        first = self.deposit()
        second = self.deposit()
        self.assertEqual((first.inserted_rows, first.inserted_events), (2, 1))
        self.assertEqual((second.inserted_rows, second.inserted_events), (0, 0))
        self.assertEqual(SupplierPayment.objects.count(), 1)
        with self.assertRaisesRegex(ImportRefused, "PII detected in evidence_ref"):
            self.payment("PII", "deposit", "1", evidence="person" + "@" + "example.com")
        with self.assertRaisesRegex(ImportRefused, "evidence_ref is required"):
            self.payment("NO-EVIDENCE", "deposit", "1", evidence="")


class EndToEndLedgerTests(SupplierPaymentBase):
    def test_po_2026_002_posts_expected_figures_and_closes(self):
        self.deposit()
        self.receive_a()
        event_a = LedgerEvent.objects.get(payload__invoice_no="INV-A")
        self.assertEqual(D(event_a.payload["deposit_applied_twd"]), D("17400.0000"))
        self.assertEqual(invoice_open(SupplierInvoice.objects.get(invoice_no="INV-A")), D("43500.0000"))
        self.payment("BAL-A", "balance", "43500.0000", invoice="INV-A", paid_on="2026-01-26")
        self.receive_b()
        event_b = LedgerEvent.objects.get(payload__invoice_no="INV-B")
        self.assertEqual(D(event_b.payload["deposit_applied_twd"]), D("21300.0000"))
        po = PurchaseOrder.objects.get(po_number="PO-2026-002")
        self.assertEqual((po.status, deposit_open(po)), ("received", D("0.0000")))
        self.payment("BAL-B", "balance", "53250.0000", invoice="INV-B", paid_on="2026-01-27")
        po.refresh_from_db()
        self.assertEqual(po.status, "closed")
        balances = {code: sum((line.debit - line.credit for line in JournalLine.objects.filter(
            account_id=code)), D(0)) for code in ("1121", "1266", "2171")}
        self.assertEqual(balances, {"1121": D("-135450.0000"), "1266": D("0.0000"),
                                    "2171": D("0.0000")})
        wac = {line.sku: line.debit / line.qty_delta_pieces for line in JournalLine.objects.filter(
            account_id="1231", entry__source_ref__contains="po.received")}
        self.assertEqual(wac, {"TS-MT-005-S": D("20.3000"), "TS-FS-004-P": D("9.9400")})
        self.assertEqual(payables("2026-01-31").rows[-1]["open"].amount, D("0.0000"))
        self.assertEqual(supplier_deposits("2026-01-31").rows[0]["open"].amount, D("0.0000"))

    def test_i4_non_terminating_rounding_and_exact_remainder(self):
        first = pro_rata_deposit(D("1000"), D("100"), D("300"))
        second = pro_rata_deposit(D("1000"), D("100"), D("300"), already=first)
        last = pro_rata_deposit(D("1000"), D("100"), D("300"), already=first + second,
                                completes=True)
        self.assertEqual((first, second, last), (D("333.3333"), D("333.3333"), D("333.3334")))

    def test_i5_stated_difference_is_recorded_listed_and_not_posted(self):
        self.deposit()
        self.receive_a(stated="17000.0000")
        event = LedgerEvent.objects.get(payload__invoice_no="INV-A")
        self.assertEqual((event.payload["deposit_applied_twd"], event.payload["invoice_stated_deposit_twd"]),
                         ("17400.0000", "17000.0000"))
        rows = deposit_reconciliation("2026-01-31").rows
        self.assertEqual((rows[0]["computed"].amount, rows[0]["stated"].amount,
                          rows[0]["difference"].amount),
                         (D("17400.0000"), D("17000.0000"), D("-400.0000")))
        applied_lines = JournalLine.objects.filter(entry=event.posted_entry, account_id__in=["2171", "1266"])
        self.assertTrue(all(line.debit == D("17400.0000") or line.credit == D("17400.0000") or
                            line.credit == D("60900.0000") for line in applied_lines))

    def test_i6_cancel_refund_forfeit_zero_and_i8_gate(self):
        self.payment("DEP-CANCEL", "deposit", "5000", paid_on="2026-01-13")
        self.cancel_po()
        self.add_settlement_source()
        failed = g2("2026-01")
        self.assertEqual(failed.status, "FAIL")
        self.assertIn("PO-2026-002=5000.0000", failed.reason)
        self.payment("REF-CANCEL", "deposit_refund", "3000", paid_on="2026-01-20")
        self.payment("FORFEIT", "deposit_forfeit", "2000", bank_ref="", paid_on="2026-01-21")
        self.assertEqual(deposit_open(PurchaseOrder.objects.get(po_number="PO-2026-002")), D("0.0000"))
        passed = g2("2026-01")
        self.assertEqual(passed.status, "PASS")
