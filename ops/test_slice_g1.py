"""Slice G-1 tests: raising a purchase order by file. A PO is a commitment; nothing posts."""

import csv
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from acct.models import JournalLine, WacPosition
from core.models import DatasetSettings
from ops.compliance import PoBlocked, assert_po_eligible
from ops.file_intake import import_po, import_products, import_suppliers, load_schema
from ops.intake import ImportRefused
from ops.models import (InventoryMove, LedgerEvent, Product, PurchaseOrder, PurchaseOrderLine,
                        PurchaseOrderStatus, Supplier)
from ops.reporting import open_pos

SAMPLES = Path(__file__).resolve().parents[1] / "docs" / "samples"
WORKBOOK_TOTALS = {"PO-2026-001": Decimal("231000"), "PO-2026-002": Decimal("129000"),
                   "PO-2026-003": Decimal("137000")}
PO_001_SELLABLE = ("TS-FL-001-S", "TS-GM-002-S", "TS-HN-007-M", "TS-SL-003-L")


def ledger_counts():
    return (LedgerEvent.objects.count(), JournalLine.objects.count(),
            InventoryMove.objects.count(), WacPosition.objects.count())


class PurchaseOrderBase(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        DatasetSettings.objects.get_or_create(pk=1, defaults={"dataset_kind": "SAMPLE"})
        import_suppliers(SAMPLES / "SAMPLE_suppliers_2026-09-27.csv", commit=True)
        import_products(SAMPLES / "SAMPLE_products_2026-09-27.csv", commit=True)
        # I-1, in every test: raising, sending, acknowledging or cancelling a PO
        # writes no LedgerEvent, JournalLine, InventoryMove or WacPosition row.
        baseline = ledger_counts()
        self.addCleanup(lambda: self.assertEqual(ledger_counts(), baseline, "a PO touched the ledger"))

    def sample_rows(self, number):
        with (SAMPLES / f"SAMPLE_po_{number}.csv").open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    def source(self, rows, filename=None, header=None):
        filename = filename or f"SAMPLE_po_{rows[0]['po_number']}.csv"
        path = Path(self.temp.name) / filename
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=header or load_schema("po")["header"])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def reference_source(self, kind, rows, filename):
        path = Path(self.temp.name) / filename
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=load_schema(kind)["header"])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def import_sample(self, number):
        return import_po(SAMPLES / f"SAMPLE_po_{number}.csv", commit=True)

    def with_status(self, number, status, **changes):
        return [{**row, "status": status, **changes} for row in self.sample_rows(number)]


class SamplePurchaseOrderTests(PurchaseOrderBase):
    def test_sample_pos_are_drafts_and_tie_to_the_workbook(self):
        for number in WORKBOOK_TOTALS:
            self.import_sample(number)
        for number, workbook_total in WORKBOOK_TOTALS.items():
            po = PurchaseOrder.objects.get(po_number=number)
            with self.subTest(po=number):
                self.assertEqual(po.status, "draft")
                self.assertEqual(po.lines.aggregate(total=Sum("line_total_twd"))["total"], workbook_total)
        rave = PurchaseOrderLine.objects.get(po__po_number="PO-2026-002", product_id="TS-FS-004-P")
        self.assertEqual((rave.qty_pieces, rave.unit_price_twd, rave.line_total_twd, rave.min_order_qty_pieces),
                         (7500, Decimal("9.0000"), Decimal("71000.0000"), 2500))
        self.assertIn("1,500 PK x 5 pieces_per_sale_unit", rave.evidence_ref)

    def test_identical_reimport_writes_zero_rows(self):
        numbers = [*WORKBOOK_TOTALS, "PO-2026-004"]
        first = [self.import_sample(number).inserted_rows for number in numbers]
        counts = (PurchaseOrder.objects.count(), PurchaseOrderLine.objects.count(),
                  PurchaseOrderStatus.objects.count())
        second = [self.import_sample(number).inserted_rows for number in numbers]
        self.assertTrue(all(first))
        self.assertEqual(second, [0, 0, 0, 0])
        self.assertEqual((PurchaseOrder.objects.count(), PurchaseOrderLine.objects.count(),
                          PurchaseOrderStatus.objects.count()), counts)

    def test_dry_run_writes_nothing(self):
        result = import_po(SAMPLES / "SAMPLE_po_PO-2026-001.csv")
        self.assertEqual((result.parsed_rows, result.would_write_rows, result.inserted_rows), (4, 6, 0))
        self.assertFalse(PurchaseOrder.objects.exists())

    def test_packaging_only_po_reaches_sent(self):
        self.import_sample("PO-2026-004")
        po = PurchaseOrder.objects.get(po_number="PO-2026-004")
        self.assertEqual(po.status, "sent")
        self.assertEqual(list(PurchaseOrderStatus.objects.filter(po_number="PO-2026-004")
                              .order_by("pk").values_list("status", flat=True)), ["draft", "sent"])

    def test_the_ledger_counter_is_not_blind(self):
        before = ledger_counts()
        InventoryMove.objects.create(product_id="TS-FL-001-S", kind="opening", qty_delta_pieces=1,
                                     value_delta_twd=1, occurred_at="2026-01-10T00:00:00Z",
                                     idempotency_key="g1-counter-probe", source_filename="synthetic",
                                     dataset_kind="SAMPLE")
        self.assertNotEqual(ledger_counts(), before)
        InventoryMove.objects.filter(idempotency_key="g1-counter-probe").delete()


class ComplianceGateTests(PurchaseOrderBase):
    def clear_po_001(self):
        suppliers = list(csv.DictReader((SAMPLES / "SAMPLE_suppliers_2026-09-27.csv").open(encoding="utf-8")))
        suppliers[0].update(declaration_ref="compliance/suppliers/SUP-001-declaration.pdf",
                            evidence_ref="declaration update")
        import_suppliers(self.reference_source("suppliers", suppliers, "SAMPLE_suppliers_2026-09-28.csv"),
                         commit=True)
        products = list(csv.DictReader((SAMPLES / "SAMPLE_products_2026-09-27.csv").open(encoding="utf-8")))
        for row in products:
            if row["sku"] in PO_001_SELLABLE:
                row.update(ingredient_ref=f"compliance/suppliers/{row['sku']}-ingredients.pdf",
                           evidence_ref="ingredient update")
        import_products(self.reference_source("products", products, "SAMPLE_products_2026-09-28.csv"),
                        commit=True)

    def test_draft_may_hold_blocked_skus_but_sent_is_refused_naming_every_one(self):
        self.import_sample("PO-2026-001")
        with self.assertRaisesRegex(
                ImportRefused,
                r"^PO PO-2026-001 cannot be sent: PO blocked for SKU\(s\): "
                r"TS-FL-001-S, TS-GM-002-S, TS-HN-007-M, TS-SL-003-L$"):
            import_po(self.source(self.with_status("PO-2026-001", "sent")), commit=True)
        self.assertEqual(PurchaseOrder.objects.get(po_number="PO-2026-001").status, "draft")

    def test_acknowledged_is_also_refused_while_blocked(self):
        with self.assertRaisesRegex(ImportRefused, "cannot be acknowledged: PO blocked"):
            import_po(self.source(self.with_status("PO-2026-001", "acknowledged")), commit=True)

    def test_cleared_sellable_po_can_be_sent(self):
        self.import_sample("PO-2026-001")
        self.clear_po_001()
        import_po(self.source(self.with_status("PO-2026-001", "sent")), commit=True)
        self.assertEqual(PurchaseOrder.objects.get(po_number="PO-2026-001").status, "sent")

    def test_packaging_needs_only_product_and_supplier(self):
        assert_po_eligible(["PKG-MAIL-LS", "PKG-CARD-LS"])
        Product.objects.create(sku="PKG-TAPE-LS", name="Orphan packaging", pieces_per_sale_unit=1,
                               product_type="packaging", ingredient_ref="NOT_APPLICABLE")
        with self.assertRaisesRegex(PoBlocked, r"^PO blocked for SKU\(s\): PKG-TAPE-LS$"):
            assert_po_eligible(["PKG-MAIL-LS", "PKG-TAPE-LS"])
        with self.assertRaisesRegex(PoBlocked, "TS-FL-001-S"):
            assert_po_eligible(["PKG-MAIL-LS", "TS-FL-001-S"])

    def test_not_applicable_is_packaging_only_in_intake_and_database(self):
        rows = list(csv.DictReader((SAMPLES / "SAMPLE_products_2026-09-27.csv").open(encoding="utf-8")))
        cases = (
            (0, {"ingredient_ref": "NOT_APPLICABLE"},
             "sellable product TS-FL-001-S ingredient_ref cannot be NOT_APPLICABLE; only packaging may carry it"),
            (10, {"ingredient_ref": "UNKNOWN"}, "packaging product PKG-MAIL-LS ingredient_ref must be NOT_APPLICABLE"),
            (10, {"product_type": "wrapping"}, "product PKG-MAIL-LS product_type must be sellable or packaging"),
            (10, {"sku": "TS-ZZ-001-S"}, "sku does not match the packaging product mapping pattern: TS-ZZ-001-S"),
        )
        for index, changes, message in cases:
            changed = [{**row, **changes} if i == index else row for i, row in enumerate(rows)]
            with self.subTest(message=message), self.assertRaisesRegex(ImportRefused, message):
                import_products(self.reference_source("products", changed, "SAMPLE_products_2026-09-28.csv"))
        for sku, product_type, ingredient in (("TS-ZZ-002-S", "sellable", "NOT_APPLICABLE"),
                                              ("PKG-ZZZ-LS", "packaging", "UNKNOWN"),
                                              ("PKG-YYY-LS", "packaging", "compliance/suppliers/x.pdf")):
            with self.subTest(sku=sku), self.assertRaises(IntegrityError), transaction.atomic():
                Product.objects.create(sku=sku, name="Invalid", pieces_per_sale_unit=1,
                                       product_type=product_type, ingredient_ref=ingredient)

    def test_a_flipped_product_type_fails_its_sku_pattern_and_v2_is_refused_by_name(self):
        # Each type has its own SKU pattern, so a product can never be re-read as the
        # other type; the immutable product_type comparison sits behind this.
        rows = list(csv.DictReader((SAMPLES / "SAMPLE_products_2026-09-27.csv").open(encoding="utf-8")))
        for index, product_type, message in ((0, "packaging", "packaging product mapping pattern: TS-FL-001-S"),
                                             (10, "sellable", "sellable product mapping pattern: PKG-MAIL-LS")):
            changed = [{**row, "product_type": product_type} if i == index else row for i, row in enumerate(rows)]
            with self.subTest(sku=rows[index]["sku"]), self.assertRaisesRegex(ImportRefused, message):
                import_products(self.reference_source("products", changed, "SAMPLE_products_2026-09-28.csv"))
        v2 = Path(self.temp.name) / "SAMPLE_products_2026-09-28.csv"
        with v2.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["sku", "name", "pieces_per_sale_unit", "supplier_ref", "ingredient_ref", "evidence_ref"])
            writer.writerow(["TS-FL-001-S", "Wildflower Fine-Line", "1", "SUP-001", "UNKNOWN", "v2"])
        with self.assertRaisesRegex(ImportRefused,
                                    r"^products file uses header v2 \(no product_type\); v3 requires product_type$"):
            import_products(v2)


class IntakeRefusalTests(PurchaseOrderBase):
    def test_named_refusals(self):
        rows = self.sample_rows("PO-2026-001")
        first = rows[0]
        cases = (
            ([{**first, "supplier_ref": "SUP-999"}, *rows[1:]], "PO PO-2026-001 has conflicting supplier_ref"),
            ([{**row, "supplier_ref": "SUP-999"} for row in rows], r"^unknown supplier_ref: SUP-999$"),
            ([{**first, "sku": "TS-ZZ-999-S"}, *rows[1:]], r"^PO PO-2026-001 has unknown sku\(s\): TS-ZZ-999-S$"),
            ([{**first, "qty_pieces": "1000", "line_total_twd": "14000.0000"}, *rows[1:]],
             r"^PO PO-2026-001 line 1 qty_pieces 1000 is below min_order_qty_pieces 2000$"),
            ([{**row, "target_delivery_date": "2026-01-09"} for row in rows],
             r"^PO PO-2026-001 target_delivery_date 2026-01-09 is before po_date 2026-01-10$"),
            ([first, {**rows[1], "line_no": "3"}, rows[2], {**rows[3], "line_no": "5"}],
             r"^PO PO-2026-001 repeats line_no 3$"),
            ([first, rows[1], rows[2], {**rows[3], "line_no": "5"}], r"^PO PO-2026-001 has line_no gaps$"),
            ([{**row, "quote_ref": " "} for row in rows],
             r"^PO PO-2026-001 quote_ref is required; a PO accepts a supplier quote$"),
            ([{**row, "po_number": "PO-2026-009"} for row in rows],
             r"^po_number PO-2026-009 does not match filename PO number PO-2026-001$"),
            ([{**row, "incoterm": "FOB Taichung"} for row in rows],
             r"^PO PO-2026-001 incoterm is not an allowed Incoterm: FOB Taichung$"),
            ([{**row, "status": "approved"} for row in rows],
             r"^PO PO-2026-001 status must be draft, sent, acknowledged or cancelled: approved$"),
            ([{**first, "evidence_ref": ""}, *rows[1:]], r"^evidence_ref is required$"),
        )
        for changed, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ImportRefused, message):
                import_po(self.source(changed, filename="SAMPLE_po_PO-2026-001.csv"), commit=True)
        self.assertFalse(PurchaseOrder.objects.exists())

    def test_filename_must_classify(self):
        with self.assertRaisesRegex(ImportRefused, "Unclassified po filename: SAMPLE_po_2026-001.csv"):
            import_po(self.source(self.sample_rows("PO-2026-001"), filename="SAMPLE_po_2026-001.csv"))

    def test_whole_pieces_only(self):
        rows = self.sample_rows("PO-2026-003")
        for qty in ("7.5", "0", "-1", ""):
            with self.subTest(qty=qty), self.assertRaisesRegex(
                    ImportRefused, r"^PO PO-2026-003 line 1 qty_pieces must be a whole number of pieces > 0$"):
                import_po(self.source([{**rows[0], "qty_pieces": qty}, rows[1]]))

    def test_no_unit_column_can_be_added(self):
        header = [*load_schema("po")["header"], "uom"]
        rows = [{**row, "uom": "PK"} for row in self.sample_rows("PO-2026-002")]
        with self.assertRaisesRegex(ImportRefused, r"expected po v1 exact columns; missing=\[\]; added=\['uom'\]"):
            import_po(self.source(rows, header=header))

    def test_line_total_is_exact_never_rounded(self):
        rows = self.sample_rows("PO-2026-001")
        with self.assertRaisesRegex(
                ImportRefused,
                r"^PO PO-2026-001 line 1 line_total_twd 62000.0100 disagrees with qty_pieces x unit_price_twd \+ "
                r"setup_charge_twd = 62000.0000$"):
            import_po(self.source([{**rows[0], "line_total_twd": "62000.0100"}, *rows[1:]]))
        with self.assertRaisesRegex(ImportRefused, "unit_price_twd must be nonnegative with at most 4 decimal places"):
            import_po(self.source([{**rows[0], "unit_price_twd": "12.00001"}, *rows[1:]]))
        with self.assertRaisesRegex(ImportRefused, r"^PO PO-2026-001 line 1 unit_price_twd must be a positive price per piece$"):
            import_po(self.source([{**rows[0], "unit_price_twd": "0", "line_total_twd": "2000.0000"}, *rows[1:]]))

    def test_currency_must_match_supplier_and_be_twd(self):
        rows = self.sample_rows("PO-2026-001")
        with self.assertRaisesRegex(ImportRefused,
                                    r"^PO PO-2026-001 currency USD must equal supplier SUP-001 currency TWD$"):
            import_po(self.source([{**row, "currency": "USD"} for row in rows]))
        Supplier.objects.create(supplier_ref="SUP-005", legal_name="Synthetic USD Supplier", country="US",
                                currency="USD", default_incoterm="EXW", payment_terms="Prepaid",
                                can_invoice_to_tax_id="unknown", evidence_ref="synthetic",
                                source_filename="SAMPLE_suppliers_2026-09-28.csv", dataset_kind="SAMPLE")
        with self.assertRaisesRegex(
                ImportRefused, r"^PO PO-2026-001 currency USD is refused: a non-TWD PO needs the FX ruling "
                               r"\(Agent 2 R-2\.6, IFRIC 22\), which does not exist yet$"):
            import_po(self.source([{**row, "currency": "USD", "supplier_ref": "SUP-005"} for row in rows]))

    def test_personal_data_is_refused_in_every_column(self):
        rows = self.sample_rows("PO-2026-003")
        for column in ("artwork_ref", "evidence_ref", "payment_terms", "quote_ref"):
            changed = [{**row, column: "ask buyer" + "@" + "example.test"} for row in rows]
            with self.subTest(column=column), self.assertRaisesRegex(ImportRefused, f"^PII detected in {column}$"):
                import_po(self.source(changed))


class LifecycleTests(PurchaseOrderBase):
    def test_forward_only_and_cancelled_is_final(self):
        self.import_sample("PO-2026-004")
        with self.assertRaisesRegex(ImportRefused, r"^PO PO-2026-004 status cannot move from sent to draft$"):
            import_po(self.source(self.with_status("PO-2026-004", "draft")), commit=True)
        import_po(self.source(self.with_status("PO-2026-004", "acknowledged")), commit=True)
        import_po(self.source(self.with_status("PO-2026-004", "cancelled")), commit=True)
        with self.assertRaisesRegex(
                ImportRefused, r"^PO PO-2026-004 status cannot move from cancelled to sent; nothing leaves cancelled$"):
            import_po(self.source(self.with_status("PO-2026-004", "sent")), commit=True)
        with self.assertRaisesRegex(ImportRefused, r"^PO PO-2026-004 is cancelled and cannot change$"):
            import_po(self.source(self.with_status("PO-2026-004", "cancelled", artwork_ref="v2.ai")), commit=True)
        self.assertEqual(list(PurchaseOrderStatus.objects.filter(po_number="PO-2026-004").order_by("pk")
                              .values_list("status", flat=True)), ["draft", "sent", "acknowledged", "cancelled"])

    def test_draft_cannot_skip_to_acknowledged_on_an_existing_po(self):
        self.import_sample("PO-2026-003")
        with self.assertRaisesRegex(ImportRefused, r"^PO PO-2026-003 status cannot move from draft to acknowledged$"):
            import_po(self.source(self.with_status("PO-2026-003", "acknowledged")), commit=True)

    def test_draft_is_editable_until_sent_then_frozen(self):
        self.import_sample("PO-2026-003")
        rows = self.sample_rows("PO-2026-003")
        edited = [{**rows[0], "qty_pieces": "16000", "line_total_twd": "106500.0000"}, rows[1]]
        self.assertEqual(import_po(self.source(edited), commit=True).inserted_rows, 1)
        sent = [{**row, "status": "sent"} for row in edited]
        import_po(self.source(sent), commit=True)
        cases = (
            ([{**row, "quote_ref": "Q-OTHER"} for row in sent], r"^PO PO-2026-003 quote_ref cannot change once sent$"),
            ([{**row, "supplier_ref": "SUP-001"} for row in sent], r"^PO PO-2026-003 supplier_ref cannot change once sent$"),
            ([{**sent[0], "qty_pieces": "15000", "line_total_twd": "100000.0000"}, sent[1]],
             r"^PO PO-2026-003 line 1 qty_pieces cannot change once sent$"),
            ([sent[0], {**sent[1], "unit_price_twd": "1.7000", "line_total_twd": "35000.0000"}],
             r"^PO PO-2026-003 line 2 unit_price_twd cannot change once sent$"),
            ([sent[0], {**sent[1], "setup_charge_twd": "0.0000", "line_total_twd": "36000.0000"}],
             r"^PO PO-2026-003 line 2 setup_charge_twd cannot change once sent$"),
            ([{**sent[0], "sku": "PKG-CARD-LS", "unit_price_twd": "1.8000", "setup_charge_twd": "0.0000",
               "line_total_twd": "28800.0000", "min_order_qty_pieces": ""}, sent[1]],
             r"^PO PO-2026-003 line 1 sku cannot change once sent$"),
            ([*sent, {**sent[1], "line_no": "3"}], r"^PO PO-2026-003 line 3 cannot be added once sent$"),
            ([sent[0]], r"^PO PO-2026-003 omits existing line_no\(s\): 2; a missing line is not a deletion$"),
        )
        for changed, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ImportRefused, message):
                import_po(self.source(changed), commit=True)
        rescheduled = [{**row, "target_delivery_date": "2026-02-05", "artwork_ref": "mailer-v2.pdf"} for row in sent]
        import_po(self.source(rescheduled), commit=True)
        po = PurchaseOrder.objects.get(po_number="PO-2026-003")
        self.assertEqual((str(po.target_delivery_date), po.status), ("2026-02-05", "sent"))
        self.assertEqual(po.lines.get(line_no=1).qty_pieces, 16000)


class DatabaseEnforcementTests(PurchaseOrderBase):
    """I-6 in the database: the intake is bypassed on purpose."""

    def setUp(self):
        super().setUp()
        self.import_sample("PO-2026-003")
        self.import_sample("PO-2026-004")
        self.draft = PurchaseOrder.objects.get(po_number="PO-2026-003")
        self.sent = PurchaseOrder.objects.get(po_number="PO-2026-004")

    def refused(self, message, action):
        with self.assertRaisesRegex(DatabaseError, message), transaction.atomic():
            action()

    def test_status_moves_need_history_and_go_forward_only(self):
        self.refused("requires its PurchaseOrderStatus history row",
                     lambda: PurchaseOrder.objects.filter(pk=self.draft.pk).update(status="sent"))
        self.refused("status cannot move from sent to draft",
                     lambda: PurchaseOrder.objects.filter(pk=self.sent.pk).update(status="draft"))
        PurchaseOrderStatus.objects.create(po_number="PO-2026-003", status="acknowledged",
                                           effective_on="2026-01-15", source_filename="synthetic",
                                           dataset_kind="SAMPLE")
        self.refused("status cannot move from draft to acknowledged",
                     lambda: PurchaseOrder.objects.filter(pk=self.draft.pk).update(status="acknowledged"))

    def test_created_as_draft_only(self):
        PurchaseOrderStatus.objects.create(po_number="PO-2026-005", status="sent", effective_on="2026-01-15",
                                           source_filename="synthetic", dataset_kind="SAMPLE")
        self.refused("is created as draft", lambda: PurchaseOrder.objects.create(
            po_number="PO-2026-005", supplier=self.sent.supplier, po_date="2026-01-15",
            target_delivery_date="2026-01-30", currency="TWD", payment_terms="Net 15 Days", incoterm="DDP",
            quote_ref="Q", status="sent", source_filename="synthetic", dataset_kind="SAMPLE"))

    def test_frozen_header_and_lines_once_sent(self):
        self.refused("frozen once sent",
                     lambda: PurchaseOrder.objects.filter(pk=self.sent.pk).update(quote_ref="changed"))
        line = self.sent.lines.get()
        self.refused("are frozen once sent",
                     lambda: PurchaseOrderLine.objects.filter(pk=line.pk).update(qty_pieces=20000,
                                                                                 line_total_twd=36000))
        self.refused("INSERT on PO-2026-004 is not permitted once the PO is sent",
                     lambda: PurchaseOrderLine.objects.create(
                         po=self.sent, line_no=2, product_id="PKG-MAIL-LS", qty_pieces=1, unit_price_twd=1,
                         setup_charge_twd=0, line_total_twd=1, evidence_ref="x", source_filename="synthetic",
                         dataset_kind="SAMPLE"))
        self.refused("DELETE on PO-2026-004 is not permitted", lambda: PurchaseOrderLine.objects.filter(
            pk=line.pk).delete())
        PurchaseOrderLine.objects.filter(pk=line.pk).update(artwork_ref="card-v3.pdf")
        # A draft's lines still change.
        PurchaseOrderLine.objects.filter(po=self.draft, line_no=2).update(qty_pieces=25000,
                                                                          line_total_twd=46000)

    def test_cancelled_is_final_and_pos_are_never_deleted(self):
        PurchaseOrderStatus.objects.create(po_number="PO-2026-004", status="cancelled",
                                           effective_on="2026-02-03", source_filename="synthetic",
                                           dataset_kind="SAMPLE")
        PurchaseOrder.objects.filter(pk=self.sent.pk).update(status="cancelled")
        self.refused("is cancelled; nothing leaves cancelled",
                     lambda: PurchaseOrder.objects.filter(pk=self.sent.pk).update(status="sent"))
        def raw_delete():
            with connection.cursor() as cursor:  # bypass Django's PROTECT to reach the trigger
                cursor.execute("DELETE FROM ops_purchaseorder WHERE id = %s", [self.draft.pk])
        self.refused("is never deleted; cancel it", raw_delete)

    def test_status_history_is_append_only(self):
        entry = PurchaseOrderStatus.objects.filter(po_number="PO-2026-004").first()
        self.refused("append-only: UPDATE", lambda: PurchaseOrderStatus.objects.filter(pk=entry.pk)
                     .update(status="cancelled"))
        self.refused("append-only: DELETE", lambda: PurchaseOrderStatus.objects.filter(pk=entry.pk).delete())
        with self.assertRaisesRegex(RuntimeError, "append-only"):
            entry.delete()

    def test_checks_on_quantity_total_currency_and_quote(self):
        line = self.draft.lines.get(line_no=1)
        for changes, name in (({"qty_pieces": 0, "line_total_twd": 2500, "min_order_qty_pieces": None},
                               "ops_po_line_positive_pieces"),
                              ({"line_total_twd": Decimal("100000.0001")}, "ops_po_line_total_identity"),
                              ({"qty_pieces": 9000, "line_total_twd": 61000}, "ops_po_line_meets_moq")):
            with self.subTest(name=name), self.assertRaisesRegex(IntegrityError, name), transaction.atomic():
                PurchaseOrderLine.objects.filter(pk=line.pk).update(**changes)
        self.refused("currency must equal the supplier currency",
                     lambda: PurchaseOrder.objects.filter(pk=self.draft.pk).update(currency="USD"))
        usd = Supplier.objects.create(supplier_ref="SUP-005", legal_name="Synthetic USD Supplier", country="US",
                                      currency="USD", default_incoterm="EXW", payment_terms="Prepaid",
                                      can_invoice_to_tax_id="unknown", evidence_ref="synthetic",
                                      source_filename="synthetic", dataset_kind="SAMPLE")
        for changes, name in (({"currency": "USD", "supplier": usd}, "ops_po_currency_twd"),
                              ({"quote_ref": ""}, "ops_po_quote_ref_required"),
                              ({"target_delivery_date": "2026-01-01"}, "ops_po_target_after_po_date")):
            with self.subTest(name=name), self.assertRaisesRegex(IntegrityError, name), transaction.atomic():
                PurchaseOrder.objects.filter(pk=self.draft.pk).update(**changes)


class OpenPurchaseOrderReportTests(PurchaseOrderBase):
    def test_committed_counts_sent_only_and_cancelled_disappears(self):
        for number in [*WORKBOOK_TOTALS, "PO-2026-004"]:
            self.import_sample(number)
        report = open_pos("2026-02-10")
        committed, drafts = report.sections
        self.assertEqual([row["po"] for row in committed.rows[:-1]], ["PO-2026-004"])
        self.assertEqual((committed.rows[-1]["pieces"].amount, committed.rows[-1]["committed"].amount),
                         (Decimal("10000"), Decimal("18000")))
        self.assertEqual(committed.rows[0]["days"].amount, Decimal("6"))
        self.assertEqual(drafts.rows[-1]["committed"].amount, sum(WORKBOOK_TOTALS.values()))
        self.assertEqual(len(drafts.rows), 9)
        import_po(self.source(self.with_status("PO-2026-004", "cancelled")), commit=True)
        committed, drafts = open_pos("2026-02-10").sections
        self.assertEqual((len(committed.rows), committed.rows[-1]["committed"].amount), (1, Decimal("0")))
        self.assertNotIn("PO-2026-004", [row["po"] for row in drafts.rows])

    def test_report_renders_with_banner_and_csv_provenance(self):
        self.import_sample("PO-2026-004")
        user = get_user_model().objects.create_user(username="po-reader", password="synthetic-pass")
        self.client.force_login(user)
        html = self.client.get(reverse("report-detail", args=["open-pos"]), {"as_of": "2026-02-10"})
        self.assertContains(html, "SAMPLE DATA — NOT ACTUALS")
        self.assertContains(html, "Drafts — not committed")
        export = self.client.get(reverse("report-detail", args=["open-pos"]),
                                 {"as_of": "2026-02-10", "format": "csv"})
        self.assertIn('filename="SAMPLE_open-pos_2026-02-10.csv"', export["Content-Disposition"])
        rows = list(csv.reader(export.content.decode().splitlines()))
        self.assertEqual(rows[0][:2], ["dataset_kind", "SAMPLE"])
        self.assertIn("committed_dataset_kind", rows[2])


class AdminTests(TestCase):
    def test_purchase_order_admin_is_read_only_with_filters(self):
        for model, filters in ((PurchaseOrder, {"supplier", "status", "lines__product"}),
                               (PurchaseOrderLine, {"po__supplier", "po__status", "product"}),
                               (PurchaseOrderStatus, {"status"})):
            model_admin = admin.site._registry[model]
            with self.subTest(model=model.__name__):
                self.assertFalse(model_admin.has_add_permission(None))
                self.assertFalse(model_admin.has_change_permission(None))
                self.assertFalse(model_admin.has_delete_permission(None))
                self.assertTrue(filters <= set(model_admin.list_filter))
