"""Slice G-2 tests: receive stock at landed cost by three-way match (PO + GRN + invoice)."""

import csv
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import reverse

from acct.models import JournalEntry, JournalLine, WacPosition
from acct.posting import PostingError, plan, post_event
from core.models import DatasetSettings
from ops.file_intake import import_po, import_products, import_suppliers, load_schema
from ops.intake import ImportRefused
from ops.landed_cost import (LandedCostError, ReceiptLineInput, allocate, assert_identity, receipt_payload,
                             value_receipt)
from ops.models import (GoodsReceipt, GoodsReceiptLine, InventoryMove, LedgerEvent, PurchaseOrder,
                        PurchaseOrderLine, PurchaseOrderStatus, SupplierInvoice, SupplierInvoiceLine)
from ops.receiving import import_grn, import_invoice
from ops.reporting import landed_cost, po_exceptions

SAMPLES = Path(__file__).resolve().parents[1] / "docs" / "samples"
TZ = ZoneInfo("Asia/Taipei")
D = Decimal


def ledger_counts():
    return (LedgerEvent.objects.count(), JournalLine.objects.count(),
            InventoryMove.objects.count(), WacPosition.objects.count())


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


class ReceivingBase(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        DatasetSettings.objects.get_or_create(pk=1, defaults={"dataset_kind": "SAMPLE"})
        import_suppliers(SAMPLES / "SAMPLE_suppliers_2026-09-27.csv", commit=True)
        import_products(SAMPLES / "SAMPLE_products_2026-09-27.csv", commit=True)
        # The gated G-1 samples: PO-003 raised as draft, then sent; PO-004 sent.
        import_po(SAMPLES / "SAMPLE_po_PO-2026-003.csv", commit=True)
        import_po(SAMPLES / "sent" / "SAMPLE_po_PO-2026-003.csv", commit=True)
        import_po(SAMPLES / "SAMPLE_po_PO-2026-004.csv", commit=True)

    def write(self, kind, rows, filename):
        path = Path(self.temp.name) / filename
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if kind is None else load_schema(kind)["header"])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def grn_rows(self):
        return read_rows(SAMPLES / "SAMPLE_grn_PO-2026-003_R1.csv")

    def inv_rows(self, **changes):
        return [{**row, **changes} for row in read_rows(SAMPLES / "SAMPLE_inv_EP-2026-0129.csv")]

    def grn(self, rows, commit=True):
        return import_grn(self.write("grn", rows, f"SAMPLE_grn_{rows[0]['po_number']}_{rows[0]['receipt_no']}.csv"),
                          commit=commit)

    def inv(self, rows, commit=True):
        return import_invoice(self.write("inv", rows, f"SAMPLE_inv_{rows[0]['invoice_no']}.csv"), commit=commit)

    def sample_grn(self):
        return import_grn(SAMPLES / "SAMPLE_grn_PO-2026-003_R1.csv", commit=True)

    def sample_inv(self):
        return import_invoice(SAMPLES / "SAMPLE_inv_EP-2026-0129.csv", commit=True)

    def entry_lines(self, receipt_no="R1", po_number="PO-2026-003"):
        event = LedgerEvent.objects.get(event_type="po.received", payload__po_number=po_number,
                                        payload__receipt_no=receipt_no)
        self.assertIsNotNone(event.posted_entry_id)
        return [(line.account_id, line.sku, line.qty_delta_pieces, line.debit, line.credit)
                for line in JournalLine.objects.filter(entry_id=event.posted_entry_id).order_by("pk")]

    def refused(self, pattern, action):
        before = ledger_counts()
        with self.assertRaisesRegex(ImportRefused, pattern):
            action()
        self.assertEqual(ledger_counts(), before)

    def declare_sellable(self, regime="general"):
        """The sellable-SKU case, built in tests only: SUP-001 and TS-FL-001-S declared."""
        suppliers = read_rows(SAMPLES / "SAMPLE_suppliers_2026-09-27.csv")
        suppliers[0].update(declaration_ref="compliance/suppliers/SUP-001-declaration.pdf",
                            evidence_ref="SAMPLE declaration for the G-2 sellable case")
        import_suppliers(self.write("suppliers", suppliers, "SAMPLE_suppliers_2026-09-28.csv"), commit=True)
        products = read_rows(SAMPLES / "SAMPLE_products_2026-09-27.csv")
        products[0].update(ingredient_ref="compliance/suppliers/TS-FL-001-S-ingredients.pdf",
                           evidence_ref="SAMPLE ingredient declaration for the G-2 sellable case")
        import_products(self.write("products", products, "SAMPLE_products_2026-09-28.csv"), commit=True)
        DatasetSettings.objects.filter(pk=1).update(business_tax_regime=regime)
        po = [{"po_number": "PO-2026-005", "supplier_ref": "SUP-001", "po_date": "2026-03-02",
               "target_delivery_date": "2026-03-20", "currency": "TWD", "payment_terms": "Net 30",
               "incoterm": "EXW", "quote_ref": "Q-SAMPLE-005", "status": "sent", "line_no": "1",
               "sku": "TS-FL-001-S", "qty_pieces": "5000", "unit_price_twd": "12.0000",
               "setup_charge_twd": "2000.0000", "line_total_twd": "62000.0000", "min_order_qty_pieces": "",
               "artwork_ref": "", "evidence_ref": "SAMPLE sellable PO for G-2 tests"}]
        import_po(self.write("po", po, "SAMPLE_po_PO-2026-005.csv"), commit=True)

    def sellable_grn(self, good="5000", damaged="0", credited="no"):
        return [{"po_number": "PO-2026-005", "receipt_no": "R1", "received_on": "2026-03-18", "line_no": "1",
                 "sku": "TS-FL-001-S", "qty_pieces_good": good, "qty_pieces_damaged": damaged,
                 "damaged_credited": credited, "short_close": "no", "short_close_reason": "",
                 "evidence_ref": "SAMPLE delivery note PO-2026-005 R1"}]

    def sellable_inv(self, qty="5000", tax="3100.0000", creditable="3100.0000", gui="AB12345678", **changes):
        amount = D(qty) * D("12.0000") + D("2000.0000")
        return [{"invoice_no": "SP-2026-0318", "gui_no": gui, "invoice_date": "2026-03-18",
                 "po_number": "PO-2026-005", "receipt_no": "R1", "line_no": "1", "sku": "TS-FL-001-S",
                 "qty_pieces_invoiced": qty, "unit_price_twd": "12.0000", "setup_charge_twd": "2000.0000",
                 "line_amount_twd": f"{amount:.4f}", "freight_twd": "0.0000", "tax_twd": tax,
                 "tax_creditable_twd": creditable, "invoice_total_twd": f"{amount + D(tax):.4f}",
                 "deposit_applied_twd": "0.0000", "evidence_ref": "SAMPLE invoice PO-2026-005 R1", **changes}]


class SampleReceiptTests(ReceivingBase):
    def test_po_003_sample_posts_the_exact_entry(self):
        self.sample_grn()
        self.assertEqual(LedgerEvent.objects.filter(event_type="po.received").count(), 0)
        result = self.sample_inv()
        self.assertEqual(result.inserted_events, 1)
        self.assertEqual(self.entry_lines(), [
            ("1233", "PKG-MAIL-LS", D("15000.0000"), D("105000.0000"), D("0.0000")),
            ("1233", "PKG-CARD-LS", D("19800.0000"), D("38461.5000"), D("0.0000")),
            ("5121", "PKG-CARD-LS", None, D("388.5000"), D("0.0000")),
            ("2171", None, None, D("0.0000"), D("143850.0000")),
        ])
        self.assertEqual(PurchaseOrder.objects.get(po_number="PO-2026-003").status, "received")
        # Packaging never enters WAC or the sellable on-hand moves.
        self.assertFalse(WacPosition.objects.exists())
        self.assertFalse(InventoryMove.objects.exists())
        rows = {row["sku"]: row for row in landed_cost("2026-01-31").rows}
        self.assertEqual(rows["PKG-MAIL-LS"]["landed"].amount, D("105000.0000"))
        self.assertEqual(rows["PKG-MAIL-LS"]["per_piece"].amount, D("7.0000"))
        self.assertEqual(rows["PKG-CARD-LS"]["landed"].amount, D("38850.0000"))
        self.assertEqual(rows["PKG-CARD-LS"]["per_piece"].amount, D("1.9425"))
        self.assertEqual(rows["PKG-CARD-LS"]["to_stock"].amount, D("38461.5000"))
        self.assertEqual(rows["PKG-CARD-LS"]["good"].amount, D("19800"))
        self.assertEqual(rows["PKG-CARD-LS"]["to_5121"].amount, D("388.5000"))
        self.assertEqual(rows["PKG-CARD-LS"]["tax"].amount, D("1850.0000"))
        self.assertEqual(rows["PKG-CARD-LS"]["setup"].amount, D("1000.0000"))

    def test_invoice_first_then_receipt_gives_the_same_entry(self):
        self.assertEqual(self.sample_inv().inserted_events, 0)
        self.assertEqual(self.sample_grn().inserted_events, 1)
        self.assertEqual(sum(line[3] for line in self.entry_lines()), D("143850.0000"))

    def test_po_004_receipt_without_invoice_posts_nothing_and_is_listed(self):
        before = ledger_counts()
        import_grn(SAMPLES / "SAMPLE_grn_PO-2026-004_R1.csv", commit=True)
        self.assertEqual(ledger_counts(), before)
        report = po_exceptions("2026-02-20")
        received = report.sections[0].rows
        self.assertEqual([(row["po"], row["receipt"], row["sku"], row["good"].amount, row["days"].amount)
                          for row in received], [("PO-2026-004", "R1", "PKG-CARD-LS", D(10000), D(6))])
        self.assertEqual(PurchaseOrder.objects.get(po_number="PO-2026-004").status, "sent")

    def test_fixture_b_supplier_freight_is_allocated_by_value_and_split_exactly(self):
        """Agent 2 rev. 5 fixture B, as the orchestrator stated it: supplier-billed freight 1,050."""
        self.sample_grn()
        self.inv(self.inv_rows(freight_twd="1050.0000", invoice_total_twd="144900.0000"))
        lines = self.entry_lines()
        self.assertEqual(lines, [
            ("1233", "PKG-MAIL-LS", D("15000.0000"), D("105766.4234"), D("0.0000")),
            ("1233", "PKG-CARD-LS", D("19800.0000"), D("38742.2408"), D("0.0000")),
            ("5121", "PKG-CARD-LS", None, D("391.3358"), D("0.0000")),
            ("2171", None, None, D("0.0000"), D("144900.0000")),
        ])
        self.assertEqual(sum(line[3] for line in lines), D("144900.0000"))
        rows = {row["sku"]: row for row in landed_cost("2026-01-31").rows}
        self.assertEqual(rows["PKG-MAIL-LS"]["per_piece"].amount, D("7.0511"))
        self.assertEqual(rows["PKG-CARD-LS"]["landed"].amount, D("39133.5766"))
        self.assertEqual(rows["PKG-CARD-LS"]["freight"].amount, D("283.5766"))
        # G.5.3: the per-piece route is NOT what was posted.
        per_piece_route = D(19800) * D("1.9567")
        self.assertEqual(per_piece_route, D("38742.6600"))
        self.assertNotEqual(lines[1][3], per_piece_route)
        self.assertEqual(per_piece_route - lines[1][3], D("0.4192"))

    def test_sellable_general_regime_debits_1268_and_1231_at_line_amount_exactly(self):
        self.declare_sellable("general")
        self.grn(self.sellable_grn())
        self.inv(self.sellable_inv())
        self.assertEqual(self.entry_lines(po_number="PO-2026-005"), [
            ("1231", "TS-FL-001-S", D("5000.0000"), D("62000.0000"), D("0.0000")),
            ("1268", None, None, D("3100.0000"), D("0.0000")),
            ("2171", None, None, D("0.0000"), D("65100.0000")),
        ])
        move = InventoryMove.objects.get(kind="received")
        self.assertEqual((move.product_id, move.qty_delta_pieces, move.value_delta_twd),
                         ("TS-FL-001-S", 5000, D("62000.0000")))

    def test_wac_for_a_sellable_sku_recomputed_by_hand_after_a_receipt(self):
        self.declare_sellable("general")
        opening_at = datetime.combine(datetime(2026, 3, 1).date(), time(12), TZ)
        opening = LedgerEvent.objects.create(
            event_type="inventory.opening_counted", entity_table="ops.stockcount", entity_id=1,
            occurred_at=opening_at, payload={"counted_at": "2026-03-01", "evidence_ref": "SAMPLE count",
                                             "lines": [{"sku": "TS-FL-001-S", "qty_pieces": "480",
                                                        "agreed_unit_cost_twd": "13.0000",
                                                        "line_value_twd": "6240.0000", "condition": "sellable"}],
                                             "total_value_twd": "6240.0000"},
            idempotency_key="g2-opening", source_filename="synthetic", dataset_kind="SAMPLE")
        post_event(opening)
        self.grn(self.sellable_grn())
        self.inv(self.sellable_inv())
        position = WacPosition.objects.get(pk="TS-FL-001-S")
        # By hand: (480 x 13.0000 + 62,000.0000) / (480 + 5,000) = 68,240 / 5,480 = 12.4526 per piece.
        self.assertEqual((position.qty_pieces, position.value_twd), (D("5480.0000"), D("68240.0000")))
        self.assertEqual((position.value_twd / position.qty_pieces).quantize(D("0.0001")), D("12.4526"))


class ThreeWayMatchTests(ReceivingBase):
    """I-1: only a three-way match posts; everything else is listed."""

    def test_receipt_against_a_draft_po_is_refused(self):
        rows = read_rows(SAMPLES / "SAMPLE_po_PO-2026-001.csv")
        import_po(SAMPLES / "SAMPLE_po_PO-2026-001.csv", commit=True)
        grn = [{"po_number": "PO-2026-001", "receipt_no": "R1", "received_on": "2026-02-01", "line_no": "1",
                "sku": rows[0]["sku"], "qty_pieces_good": rows[0]["qty_pieces"], "qty_pieces_damaged": "0",
                "damaged_credited": "no", "short_close": "no", "short_close_reason": "", "evidence_ref": "x"}]
        self.refused(r"^PO PO-2026-001 is draft; a goods receipt is accepted only against a sent or "
                     r"acknowledged PO$", lambda: self.grn(grn))

    def test_invoice_without_receipt_is_listed_and_posts_nothing(self):
        before = ledger_counts()
        self.sample_inv()
        self.assertEqual(ledger_counts(), before)
        report = po_exceptions("2026-01-31")
        self.assertEqual([(row["po"], row["receipt"], row["invoice"]) for row in report.sections[1].rows],
                         [("PO-2026-003", "R1", "EP-2026-0129")])
        self.assertEqual(report.sections[0].rows, [])

    def test_disagreeing_pair_posts_nothing_and_is_listed_with_its_reason(self):
        rows = self.grn_rows()
        # The 200 damaged cards are credited, so the supplier should bill 19,800; the sample invoice bills 20,000.
        rows[1].update(damaged_credited="yes", short_close="yes",
                       short_close_reason="200 damaged cards credited; not re-sent")
        self.grn(rows)
        before = ledger_counts()
        result = self.sample_inv()
        self.assertEqual(ledger_counts(), before)
        expected = ("INV EP-2026-0129 against GRN PO-2026-003/R1 line 2: invoiced 20000 pieces but received "
                    "good 19800 + damaged not credited 0 = 19800")
        self.assertEqual(result.match_refusals, [expected])
        self.assertEqual([row["reason"] for row in po_exceptions("2026-01-31").sections[2].rows], [expected])
        self.assertEqual(PurchaseOrder.objects.get(po_number="PO-2026-003").status, "sent")

    def test_line_sets_that_differ_are_a_refused_match(self):
        self.grn(self.grn_rows()[:1])
        rows = self.inv_rows()
        self.inv(rows)
        reasons = [row["reason"] for row in po_exceptions("2026-01-31").sections[2].rows]
        self.assertEqual(reasons, ["INV EP-2026-0129 against GRN PO-2026-003/R1: invoice lines [1, 2] do not "
                                   "match receipt lines [1]"])
        self.assertFalse(LedgerEvent.objects.exists())

    def test_dry_run_writes_nothing(self):
        before = (ledger_counts(), GoodsReceipt.objects.count(), SupplierInvoice.objects.count())
        self.assertEqual(import_grn(SAMPLES / "SAMPLE_grn_PO-2026-003_R1.csv").would_write_rows, 3)
        self.assertEqual(import_invoice(SAMPLES / "SAMPLE_inv_EP-2026-0129.csv").would_write_rows, 3)
        self.assertEqual((ledger_counts(), GoodsReceipt.objects.count(), SupplierInvoice.objects.count()), before)


class IdentityTests(ReceivingBase):
    """I-2: the G.5.1 identity, exact to 0.0001, at emission and in the posting rule."""

    def payload(self):
        values = value_receipt([
            ReceiptLineInput(1, "PKG-MAIL-LS", "1233", 15000, 0, D("100000"), D("2500")),
            ReceiptLineInput(2, "PKG-CARD-LS", "1233", 19800, 200, D("37000"), D("1000"))],
            freight=D(0), tax=D("6850"), tax_creditable=D(0))
        return receipt_payload(values, po_number="PO-2026-003", receipt_no="R1", invoice_no="EP-2026-0129",
                               gui_no="", supplier_total=D("143850"), tax=D("6850"), tax_creditable=D(0))

    def event(self, payload):
        return LedgerEvent(event_type="po.received", entity_table="ops.goodsreceipt", entity_id=1,
                           occurred_at=datetime(2026, 1, 29, 12, tzinfo=TZ), currency="TWD", payload=payload,
                           idempotency_key="identity", source_filename="synthetic", dataset_kind="SAMPLE")

    def test_the_identity_holds_and_is_watched_at_one_ten_thousandth(self):
        payload = self.payload()
        assert_identity(payload)
        self.assertEqual(sum(line.debit - line.credit for line in plan(self.event(payload))), 0)
        payload["damaged_on_arrival"][0]["landed_cost_twd"] = "388.5001"
        with self.assertRaisesRegex(LandedCostError, r"identity fails: .* = 143850.0001 .* = 143850.0000"):
            assert_identity(payload)
        with self.assertRaisesRegex(PostingError, r"po.received identity fails by 0.0001 TWD"):
            plan(self.event(payload))

    def test_emission_asserts_the_identity(self):
        values = value_receipt([ReceiptLineInput(1, "PKG-MAIL-LS", "1233", 15000, 0, D("100000"), D("2500"))],
                               freight=D(0), tax=D("5000"), tax_creditable=D(0))
        with self.assertRaisesRegex(LandedCostError, "identity fails"):
            receipt_payload(values, po_number="PO-2026-003", receipt_no="R1", invoice_no="X", gui_no="",
                            supplier_total=D("105000.0001"), tax=D("5000"), tax_creditable=D(0))


class AllocationTests(ReceivingBase):
    """I-3: line amount + by-value shares; remainder to the highest PO line number; carrier refused."""

    def test_remainder_goes_to_the_highest_po_line_number_not_the_last_row(self):
        self.assertEqual(allocate(D(1), {3: D(1), 1: D(1), 2: D(1)}),
                         {1: D("0.3333"), 2: D("0.3333"), 3: D("0.3334")})
        po = [{"po_number": "PO-2026-006", "supplier_ref": "SUP-003", "po_date": "2026-02-02",
               "target_delivery_date": "2026-02-16", "currency": "TWD", "payment_terms": "Net 15 Days",
               "incoterm": "DDP", "quote_ref": "Q-SAMPLE-006", "status": "sent", "line_no": str(n),
               "sku": sku, "qty_pieces": "1000", "unit_price_twd": "6.5000", "setup_charge_twd": "0.0000",
               "line_total_twd": "6500.0000", "min_order_qty_pieces": "", "artwork_ref": "",
               "evidence_ref": "SAMPLE three equal lines"}
              for n, sku in ((1, "PKG-MAIL-LS"), (2, "PKG-CARD-LS"), (3, "PKG-CARD-LS"))]
        import_po(self.write("po", po, "SAMPLE_po_PO-2026-006.csv"), commit=True)
        grn = [{"po_number": "PO-2026-006", "receipt_no": "R1", "received_on": "2026-02-10", "line_no": str(n),
                "sku": sku, "qty_pieces_good": "1000", "qty_pieces_damaged": "0", "damaged_credited": "no",
                "short_close": "no", "short_close_reason": "", "evidence_ref": "x"}
               for n, sku in ((3, "PKG-CARD-LS"), (2, "PKG-CARD-LS"), (1, "PKG-MAIL-LS"))]  # reversed rows
        self.grn(grn)
        inv = [{"invoice_no": "EP-2026-0210", "gui_no": "", "invoice_date": "2026-02-10", "po_number": "PO-2026-006",
                "receipt_no": "R1", "line_no": row["line_no"], "sku": row["sku"], "qty_pieces_invoiced": "1000",
                "unit_price_twd": "6.5000", "setup_charge_twd": "0.0000", "line_amount_twd": "6500.0000",
                "freight_twd": "1.0000", "tax_twd": "0.0000", "tax_creditable_twd": "0.0000",
                "invoice_total_twd": "19501.0000", "deposit_applied_twd": "0.0000", "evidence_ref": "x"}
               for row in grn]
        self.inv(inv)
        shares = {row["line"]: row["freight"].amount for row in landed_cost("2026-02-28").rows}
        self.assertEqual(shares, {"1": D("0.3333"), "2": D("0.3333"), "3": D("0.3334")})

    def test_stated_per_line_tax_wins_over_value(self):
        lines = [ReceiptLineInput(1, "A", "1231", 10, 0, D("100"), D(0), stated_tax=D("0")),
                 ReceiptLineInput(2, "B", "1231", 10, 0, D("100"), D(0), stated_tax=D("10"))]
        values = value_receipt(lines, freight=D(0), tax=D("10"), tax_creditable=D(0))
        self.assertEqual([value.tax_share for value in values], [D("0.0000"), D("10.0000")])
        by_value = value_receipt([ReceiptLineInput(1, "A", "1231", 10, 0, D("100"), D(0)),
                                  ReceiptLineInput(2, "B", "1231", 10, 0, D("100"), D(0))],
                                 freight=D(0), tax=D("10"), tax_creditable=D(0))
        self.assertEqual([value.tax_share for value in by_value], [D("5.0000"), D("5.0000")])

    def test_carrier_freight_or_duty_is_refused_naming_slice_i(self):
        self.sample_grn()
        for column in ("carrier_freight_twd", "duty_twd"):
            rows = [{**row, column: "100.0000"} for row in self.inv_rows()]
            with self.subTest(column=column):
                self.refused(rf"carries carrier freight or duty \({column}\); carrier freight and duty on a "
                             r"receipt arrive in Slice I", lambda: self.inv_with_header(rows))
        grn = [{**row, "duty_twd": "5"} for row in self.grn_rows()]
        path = self.write(None, grn, "SAMPLE_grn_PO-2026-003_R2.csv")
        self.refused(r"arrive in Slice I", lambda: import_grn(path, commit=True))
        payload = IdentityTests.payload(self)
        payload["landed_components_twd"]["freight"] = "1050.0000"
        with self.assertRaisesRegex(PostingError, "carrier freight and duty on a receipt arrive in Slice I"):
            plan(IdentityTests.event(self, payload))

    def inv_with_header(self, rows):
        return import_invoice(self.write(None, rows, "SAMPLE_inv_EP-2026-0129.csv"), commit=True)


class DamageTests(ReceivingBase):
    """I-4: damaged value by the exact split; no quantity enters WAC; credited pieces appear nowhere."""

    def test_damaged_sellable_pieces_go_to_5121_and_add_no_wac_quantity(self):
        self.declare_sellable("general")
        self.grn(self.sellable_grn(good="4950", damaged="50"))
        self.inv(self.sellable_inv())
        self.assertEqual(self.entry_lines(po_number="PO-2026-005"), [
            ("1231", "TS-FL-001-S", D("4950.0000"), D("61380.0000"), D("0.0000")),
            ("5121", "TS-FL-001-S", None, D("620.0000"), D("0.0000")),
            ("1268", None, None, D("3100.0000"), D("0.0000")),
            ("2171", None, None, D("0.0000"), D("65100.0000")),
        ])
        position = WacPosition.objects.get(pk="TS-FL-001-S")
        self.assertEqual((position.qty_pieces, position.value_twd), (D("4950.0000"), D("61380.0000")))
        self.assertEqual(InventoryMove.objects.get().qty_delta_pieces, 4950)

    def test_split_is_value_times_ratio_never_qty_times_rounded_per_piece(self):
        values = value_receipt([ReceiptLineInput(2, "PKG-CARD-LS", "1233", 19800, 200, D("39133.5766"), D(0))],
                               freight=D(0), tax=D(0), tax_creditable=D(0))
        self.assertEqual((values[0].damaged_value, values[0].good_value), (D("391.3358"), D("38742.2408")))
        self.assertEqual(values[0].damaged_value + values[0].good_value, D("39133.5766"))

    def test_credited_damaged_pieces_appear_nowhere(self):
        rows = self.grn_rows()
        rows[1].update(damaged_credited="yes", short_close="yes",
                       short_close_reason="200 damaged cards credited by the supplier")
        self.grn(rows)
        inv = self.inv_rows(tax_twd="6832.0000", invoice_total_twd="143472.0000")
        inv[1].update(qty_pieces_invoiced="19800", line_amount_twd="36640.0000")
        self.inv(inv)
        lines = self.entry_lines()
        self.assertEqual([line[0] for line in lines], ["1233", "1233", "2171"])
        event = LedgerEvent.objects.get(event_type="po.received")
        self.assertEqual(event.payload["damaged_on_arrival"], [])
        self.assertEqual(PurchaseOrder.objects.get(po_number="PO-2026-003").status, "short_closed")


class TaxTests(ReceivingBase):
    """I-5: tax and creditable required; 0 <= creditable <= tax; creditable needs a GUI and a regime."""

    def test_tax_fields_are_required(self):
        self.sample_grn()
        for column in ("tax_twd", "tax_creditable_twd"):
            with self.subTest(column=column):
                self.refused(rf"^{column} is required$", lambda: self.inv(self.inv_rows(**{column: ""})))

    def test_creditable_bounds_gui_and_regime(self):
        self.declare_sellable("unregistered")
        self.grn(self.sellable_grn())
        self.refused(r"^INV SP-2026-0318 tax_creditable_twd 3200.0000 exceeds tax_twd 3100.0000$",
                     lambda: self.inv(self.sellable_inv(creditable="3200.0000")))
        self.refused(r"^INV SP-2026-0318 tax_creditable_twd > 0 requires a gui_no; a blank gui_no means the "
                     r"tax is not creditable \(catalogue G.1\)$", lambda: self.inv(self.sellable_inv(gui="")))
        self.refused(r"^INV SP-2026-0318 tax_creditable_twd > 0 requires business_tax_regime assessed or "
                     r"general; this dataset is unregistered \(catalogue G.5.6\)$",
                     lambda: self.inv(self.sellable_inv()))
        self.refused(r"^INV SP-2026-0318 gui_no must be blank or two letters and eight digits$",
                     lambda: self.inv(self.sellable_inv(gui="12345")))
        # Unregistered with a GUI present: nothing is creditable; the tax is capitalised.
        self.inv(self.sellable_inv(creditable="0.0000"))
        self.assertEqual(self.entry_lines(po_number="PO-2026-005"), [
            ("1231", "TS-FL-001-S", D("5000.0000"), D("65100.0000"), D("0.0000")),
            ("2171", None, None, D("0.0000"), D("65100.0000")),
        ])

    def test_the_posting_rule_refuses_creditable_tax_when_unregistered_or_without_gui(self):
        payload = IdentityTests.payload(self)
        payload["tax_creditable_twd"] = "6850.0000"
        payload["landed_components_twd"]["supplier"] = "150700.0000"
        event = IdentityTests.event(self, payload)
        with self.assertRaisesRegex(PostingError, "creditable input tax requires a gui_no"):
            plan(event)
        payload["gui_no"] = "AB12345678"
        with self.assertRaisesRegex(PostingError, "requires business_tax_regime assessed or general"):
            plan(event)
        del payload["tax_twd"]
        with self.assertRaisesRegex(PostingError, "required payload field tax_twd is missing"):
            plan(event)

    def test_database_holds_creditable_rules(self):
        self.sample_inv()
        invoice = SupplierInvoice.objects.get()
        for name, changes in (("ops_invoice_creditable_within_tax", {"tax_creditable_twd": D("9999"),
                                                                      "gui_no": "AB12345678"}),
                              ("ops_invoice_creditable_needs_gui", {"tax_creditable_twd": D("1")})):
            with self.subTest(name=name), self.assertRaisesRegex(IntegrityError, name), transaction.atomic():
                SupplierInvoice.objects.create(**{**{f.attname: getattr(invoice, f.attname)
                                                     for f in SupplierInvoice._meta.concrete_fields
                                                     if f.attname != "id"},
                                                  "invoice_no": "OTHER", "receipt_no": "R9", **changes})


class PriceTests(ReceivingBase):
    """I-6: the invoice matches the PO exactly on sku, unit price and setup."""

    def test_variances_are_refused_by_name(self):
        self.sample_grn()
        cases = (
            ({"unit_price_twd": "6.6000", "line_amount_twd": "101500.0000"}, 0,
             r"^INV EP-2026-0129 line 1 unit_price_twd 6.6000 disagrees with PO PO-2026-003 line 1 "
             r"unit_price_twd 6.5000; a price variance is refused, not absorbed \(the PO is frozen once sent\)$"),
            ({"setup_charge_twd": "1200.0000", "line_amount_twd": "37200.0000"}, 1,
             r"^INV EP-2026-0129 line 2 setup_charge_twd 1200.0000 disagrees with PO PO-2026-003 line 2 "
             r"setup_charge_twd 1000.0000; a price variance is refused"),
            ({"sku": "PKG-MAIL-LS"}, 1,
             r"^INV EP-2026-0129 line 2 sku PKG-MAIL-LS disagrees with PO PO-2026-003 line 2 sku PKG-CARD-LS$"),
            ({"line_amount_twd": "37000.0001"}, 1,
             r"^INV EP-2026-0129 line 2 line_amount_twd 37000.0001 disagrees with qty_pieces_invoiced x "
             r"unit_price_twd \+ setup_charge_twd = 37000.0000$"),
        )
        for changes, index, pattern in cases:
            rows = self.inv_rows()
            rows[index].update(changes)
            total = sum(D(row["line_amount_twd"]) for row in rows) + D("6850")
            rows = [{**row, "invoice_total_twd": f"{total:.4f}"} for row in rows]
            with self.subTest(pattern=pattern):
                self.refused(pattern, lambda: self.inv(rows))
        self.refused(r"^INV EP-2026-0129 invoice_total_twd 143850.0001 disagrees with sum\(line_amount_twd\) \+ "
                     r"freight_twd \+ tax_twd = 143850.0000$",
                     lambda: self.inv(self.inv_rows(invoice_total_twd="143850.0001")))


class DeliveryTests(ReceivingBase):
    """I-7: one receipt per PO line; short deliveries close the line; overs allowed when invoiced."""

    def test_a_second_receipt_against_a_line_is_refused(self):
        self.sample_grn()
        rows = [{**row, "receipt_no": "R2"} for row in self.grn_rows()]
        self.refused(r"^PO PO-2026-003 line 1 already has receipt R1; multi-delivery lines arrive in G-2b$",
                     lambda: self.grn(rows))
        receipt = GoodsReceipt.objects.create(po=PurchaseOrder.objects.get(po_number="PO-2026-003"),
                                              receipt_no="R3", received_on="2026-01-30",
                                              source_filename="synthetic", dataset_kind="SAMPLE")
        line = GoodsReceiptLine.objects.get(line_no=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GoodsReceiptLine.objects.create(receipt=receipt, po_line=line.po_line, line_no=1,
                                            product_id="PKG-MAIL-LS", qty_pieces_good=1, qty_pieces_damaged=0,
                                            damaged_credited=False, short_close=False, evidence_ref="x",
                                            source_filename="synthetic", dataset_kind="SAMPLE")

    def test_short_delivery_must_close_the_line_with_a_reason(self):
        rows = self.grn_rows()
        rows[0]["qty_pieces_good"] = "14000"
        self.refused(r"^GRN PO-2026-003/R1 line 1 accepts 14000 of 15000 ordered pieces; a short delivery "
                     r"closes the line: short_close=yes with a short_close_reason \(multi-delivery lines arrive "
                     r"in G-2b\)$", lambda: self.grn(rows))
        rows[0]["short_close"] = "yes"
        self.refused(r"^GRN PO-2026-003/R1 line 1 short_close=yes needs a short_close_reason$",
                     lambda: self.grn(rows))
        full = self.grn_rows()
        full[0].update(short_close="yes", short_close_reason="x")
        self.refused(r"^GRN PO-2026-003/R1 line 1 short_close=yes but the line is not short \(15000 of 15000 "
                     r"ordered pieces\)$", lambda: self.grn(full))

    def test_short_closed_line_capitalises_setup_over_pieces_received(self):
        rows = self.grn_rows()
        rows[0].update(qty_pieces_good="14000", short_close="yes", short_close_reason="printer ran short; closed")
        self.grn(rows)
        inv = self.inv_rows(tax_twd="6525.0000", invoice_total_twd="137025.0000")
        inv[0].update(qty_pieces_invoiced="14000", line_amount_twd="93500.0000")
        self.inv(inv)
        mailers = {row["sku"]: row for row in landed_cost("2026-01-31").rows}["PKG-MAIL-LS"]
        # (14,000 x 6.50 + 2,500 setup) + 5% tax by value = 98,175 over 14,000 pieces = 7.0125 per piece.
        self.assertEqual((mailers["landed"].amount, mailers["per_piece"].amount), (D("98175.0000"), D("7.0125")))
        self.assertEqual(PurchaseOrder.objects.get(po_number="PO-2026-003").status, "short_closed")
        self.assertEqual(list(PurchaseOrderStatus.objects.filter(po_number="PO-2026-003").order_by("pk")
                              .values_list("status", flat=True)), ["draft", "sent", "short_closed"])

    def test_overs_are_allowed_when_invoiced(self):
        rows = self.grn_rows()
        rows[0]["qty_pieces_good"] = "15300"
        self.grn(rows)
        inv = self.inv_rows(tax_twd="6947.5000", invoice_total_twd="145897.5000")
        inv[0].update(qty_pieces_invoiced="15300", line_amount_twd="101950.0000")
        self.inv(inv)
        self.assertEqual(self.entry_lines()[0][2], D("15300.0000"))
        self.assertEqual(PurchaseOrder.objects.get(po_number="PO-2026-003").status, "received")


class DepositTests(ReceivingBase):
    def test_g3_records_invoice_stated_deposit_without_posting_it(self):
        # Touched in G-3: G-2's temporary refusal is intentionally lifted by Addendum H.2.
        self.sample_grn()
        self.inv(self.inv_rows(deposit_applied_twd="1000.0000"))
        invoice = SupplierInvoice.objects.get(invoice_no="EP-2026-0129")
        event = LedgerEvent.objects.get(payload__invoice_no="EP-2026-0129")
        self.assertEqual(invoice.deposit_applied_twd, D("1000.0000"))
        self.assertEqual(event.payload["invoice_stated_deposit_twd"], "1000.0000")
        self.assertEqual(event.payload["deposit_applied_twd"], "0.0000")


class IdempotencyTests(ReceivingBase):
    """I-9: identical re-import of any file inserts zero rows and emits zero events."""

    def test_identical_reimports_write_nothing(self):
        self.sample_grn()
        self.sample_inv()
        import_grn(SAMPLES / "SAMPLE_grn_PO-2026-004_R1.csv", commit=True)
        counts = (ledger_counts(), GoodsReceipt.objects.count(), GoodsReceiptLine.objects.count(),
                  SupplierInvoice.objects.count(), SupplierInvoiceLine.objects.count(),
                  PurchaseOrderStatus.objects.count(), JournalEntry.objects.count())
        for importer, path in ((import_grn, SAMPLES / "SAMPLE_grn_PO-2026-003_R1.csv"),
                               (import_invoice, SAMPLES / "SAMPLE_inv_EP-2026-0129.csv"),
                               (import_grn, SAMPLES / "SAMPLE_grn_PO-2026-004_R1.csv"),
                               (import_po, SAMPLES / "sent" / "SAMPLE_po_PO-2026-003.csv"),
                               (import_po, SAMPLES / "SAMPLE_po_PO-2026-004.csv")):
            with self.subTest(path=path.name):
                result = importer(path, commit=True)
                self.assertEqual((result.inserted_rows, result.inserted_events), (0, 0))
        self.assertEqual((ledger_counts(), GoodsReceipt.objects.count(), GoodsReceiptLine.objects.count(),
                          SupplierInvoice.objects.count(), SupplierInvoiceLine.objects.count(),
                          PurchaseOrderStatus.objects.count(), JournalEntry.objects.count()), counts)

    def test_reimporting_a_posted_receipt_on_a_partly_received_po_writes_nothing(self):
        # The PO stays sent while line 2 is outstanding, so only the event guard stops a replay.
        self.declare_sellable("general")
        po = [{"po_number": "PO-2026-007", "supplier_ref": "SUP-001", "po_date": "2026-03-02",
               "target_delivery_date": "2026-03-20", "currency": "TWD", "payment_terms": "Net 30",
               "incoterm": "EXW", "quote_ref": "Q-SAMPLE-007", "status": "sent", "line_no": str(n),
               "sku": "TS-FL-001-S", "qty_pieces": "1000", "unit_price_twd": "12.0000",
               "setup_charge_twd": "0.0000", "line_total_twd": "12000.0000", "min_order_qty_pieces": "",
               "artwork_ref": "", "evidence_ref": "SAMPLE two-line sellable PO"} for n in (1, 2)]
        import_po(self.write("po", po, "SAMPLE_po_PO-2026-007.csv"), commit=True)
        grn = [{**self.sellable_grn(good="1000")[0], "po_number": "PO-2026-007"}]
        inv = [{**self.sellable_inv(qty="1000", tax="0.0000", creditable="0.0000", gui="")[0],
                "po_number": "PO-2026-007", "setup_charge_twd": "0.0000", "line_amount_twd": "12000.0000",
                "invoice_total_twd": "12000.0000", "invoice_no": "SP-2026-0007"}]
        self.grn(grn)
        self.assertEqual(self.inv(inv).inserted_events, 1)
        self.assertEqual(PurchaseOrder.objects.get(po_number="PO-2026-007").status, "sent")
        counts = (ledger_counts(), PurchaseOrderStatus.objects.count())
        for result in (self.grn(grn), self.inv(inv)):
            self.assertEqual((result.inserted_rows, result.inserted_events, result.match_refusals), (0, 0, []))
        self.assertEqual((ledger_counts(), PurchaseOrderStatus.objects.count()), counts)

    def test_changed_reimports_are_refused(self):
        self.sample_grn()
        self.sample_inv()
        rows = self.grn_rows()
        rows[0]["evidence_ref"] = "a different delivery note"
        self.refused(r"^Previously imported goods receipt PO-2026-003/R1 has changed; goods receipts are "
                     r"append-only$", lambda: self.grn(rows))
        self.refused(r"^Previously imported supplier invoice EP-2026-0129 has changed; supplier invoices are "
                     r"append-only$", lambda: self.inv(self.inv_rows(invoice_date="2026-01-30")))
        self.refused(r"^PO PO-2026-003 is received and cannot change$", lambda: import_po(self.write(
            "po", [{**row, "status": "cancelled"} for row in read_rows(SAMPLES / "SAMPLE_po_PO-2026-003.csv")],
            "SAMPLE_po_PO-2026-003.csv"), commit=True))


class PersonalDataTests(ReceivingBase):
    def test_pii_in_any_column_is_refused_without_echo(self):
        grn = self.grn_rows()
        grn[0]["short_close_reason"] = "ask " + "@".join(("buyer", "example.com"))
        self.refused(r"^PII detected in short_close_reason$", lambda: self.grn(grn))
        inv = self.inv_rows(evidence_ref="sent by @printer_handle")
        self.refused(r"^PII detected in evidence_ref$", lambda: self.inv(inv))
        for column in load_schema("grn")["header"]:
            rows = self.grn_rows()
            rows[0][column] = "@".join(("a", "b.co"))
            with self.subTest(column=column):
                self.refused(rf"^PII detected in {column}$", lambda: self.write_and_import_grn(rows))

    def write_and_import_grn(self, rows):
        return import_grn(self.write("grn", rows, "SAMPLE_grn_PO-2026-003_R1.csv"), commit=True)


class InTransitTests(ReceivingBase):
    def test_a_po_with_an_in_transit_event_is_refused_naming_g2b(self):
        po = PurchaseOrder.objects.get(po_number="PO-2026-003")
        LedgerEvent.objects.create(event_type="po.in_transit", entity_table="ops.purchaseorder", entity_id=po.pk,
                                   occurred_at=datetime(2026, 1, 25, 12, tzinfo=TZ), amount_minor=1000,
                                   currency="TWD", payload={"po_number": "PO-2026-003"},
                                   idempotency_key="synthetic-in-transit", source_filename="synthetic",
                                   dataset_kind="SAMPLE")
        self.refused(r"^PO PO-2026-003 has a po.in_transit event; a receipt after goods in transit arrives in "
                     r"G-2b \(catalogue G.5.5\)$", self.sample_grn)
        payload = IdentityTests.payload(self)
        payload["landed_components_twd"]["in_transit"] = "1.0000"
        with self.assertRaisesRegex(PostingError, "arrives in G-2b"):
            plan(IdentityTests.event(self, payload))


class DatabaseEnforcementTests(ReceivingBase):
    """The intake is bypassed on purpose."""

    def refused_sql(self, message, sql, params=()):
        with self.assertRaisesRegex(DatabaseError, message), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, params)

    def test_documents_are_append_only(self):
        self.sample_grn()
        self.sample_inv()
        for table in ("ops_goodsreceipt", "ops_goodsreceiptline", "ops_supplierinvoice", "ops_supplierinvoiceline"):
            with self.subTest(table=table):
                self.refused_sql(f"{table} is append-only: UPDATE", f"UPDATE {table} SET source_filename = 'x'")
                self.refused_sql(f"{table} is append-only: DELETE", f"DELETE FROM {table}")
        with self.assertRaisesRegex(RuntimeError, "append-only"):
            GoodsReceipt.objects.get().save()

    def test_received_is_reached_only_when_every_line_is_received_and_only_moves_to_closed(self):
        po = PurchaseOrder.objects.get(po_number="PO-2026-004")
        PurchaseOrderStatus.objects.create(po_number="PO-2026-004", status="received", effective_on="2026-02-14",
                                           source_filename="synthetic", dataset_kind="SAMPLE")
        self.refused_sql("cannot be received until every line is received",
                         "UPDATE ops_purchaseorder SET status = 'received' WHERE id = %s", [po.pk])
        import_grn(SAMPLES / "SAMPLE_grn_PO-2026-004_R1.csv", commit=True)
        PurchaseOrderStatus.objects.create(po_number="PO-2026-004", status="cancelled", effective_on="2026-02-14",
                                           source_filename="synthetic", dataset_kind="SAMPLE")
        self.refused_sql("has goods received and cannot be cancelled",
                         "UPDATE ops_purchaseorder SET status = 'cancelled' WHERE id = %s", [po.pk])
        self.sample_grn()
        self.sample_inv()
        received = PurchaseOrder.objects.get(po_number="PO-2026-003")
        # Touched in G-3: received is no longer terminal, but its only forward move is closed.
        self.refused_sql("is received; it may move only to closed",
                         "UPDATE ops_purchaseorder SET payment_terms = 'x' WHERE id = %s", [received.pk])

    def test_a_document_line_must_belong_to_its_own_po(self):
        import_grn(SAMPLES / "SAMPLE_grn_PO-2026-004_R1.csv", commit=True)
        receipt = GoodsReceipt.objects.get()
        other = PurchaseOrderLine.objects.get(po__po_number="PO-2026-003", line_no=2)
        with self.assertRaisesRegex(DatabaseError, "must be a line of its own PO"), transaction.atomic():
            GoodsReceiptLine.objects.create(receipt=receipt, po_line=other, line_no=2, product_id="PKG-CARD-LS",
                                            qty_pieces_good=1, qty_pieces_damaged=0, damaged_credited=False,
                                            short_close=False, evidence_ref="x", source_filename="synthetic",
                                            dataset_kind="SAMPLE")

    def test_cancelling_a_po_with_goods_received_is_refused_at_intake(self):
        import_grn(SAMPLES / "SAMPLE_grn_PO-2026-004_R1.csv", commit=True)
        rows = [{**row, "status": "cancelled"} for row in read_rows(SAMPLES / "SAMPLE_po_PO-2026-004.csv")]
        self.refused(r"^PO PO-2026-004 has goods received and cannot be cancelled$",
                     lambda: import_po(self.write("po", rows, "SAMPLE_po_PO-2026-004.csv"), commit=True))


class ReportViewTests(ReceivingBase):
    def test_reports_render_with_the_sample_banner_and_provenance(self):
        self.sample_grn()
        self.sample_inv()
        import_grn(SAMPLES / "SAMPLE_grn_PO-2026-004_R1.csv", commit=True)
        user = get_user_model().objects.create_user(username="g2-reader", password="synthetic-pass")
        self.client.force_login(user)
        for slug, text in (("po-exceptions", "PO-2026-004"), ("landed-cost", "NT$1.9425/pc")):
            with self.subTest(slug=slug):
                html = self.client.get(reverse("report-detail", args=[slug]), {"as_of": "2026-02-20"})
                self.assertContains(html, "SAMPLE DATA — NOT ACTUALS")
                self.assertContains(html, text)
                export = self.client.get(reverse("report-detail", args=[slug]),
                                         {"as_of": "2026-02-20", "format": "csv"})
                self.assertIn(f'filename="SAMPLE_{slug}_2026-02-20.csv"', export["Content-Disposition"])
        index = self.client.get(reverse("report-index"))
        self.assertContains(index, "Purchase exceptions")
        self.assertContains(index, "Landed cost by PO line")
