"""Slice R-2: damaged count rows are custody memos, never inventory value or quantity."""

import csv
from datetime import datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase

from acct.models import Account, JournalEntry, JournalLine, WacPosition
from acct.posting import PostingError, plan, post_event
from acct.reporting import inventory_roll_forward
from core.models import DatasetSettings
from ops.file_intake import import_counts, load_schema
from ops.intake import ImportRefused
from ops.models import InventoryMove, LedgerEvent, OnHand, Product, StockCountLine


D = Decimal
TZ = ZoneInfo("Asia/Taipei")


class DamagedCountRefusalTests(TestCase):
    def setUp(self):
        DatasetSettings.objects.update_or_create(pk=1, defaults={"dataset_kind": "SAMPLE"})
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        Product.objects.create(sku="COUNT-A", name="Synthetic", uom="PC", pieces_per_sale_unit=1)

    def row(self, *, sku="COUNT-A", qty="10", cost="10.0000", condition="sellable"):
        return {"counted_at": "2026-10-04", "evidence_ref": "COUNT-R2", "sku": sku,
                "qty_pieces": qty, "agreed_unit_cost_twd": cost, "condition": condition}

    def source(self, rows, name="SAMPLE_count_2026-10-04.csv"):
        path = Path(self.temp.name) / name
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=load_schema("counts")["header"])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def assert_refused(self, rows, message):
        with self.assertRaisesRegex(ImportRefused, message):
            import_counts(self.source(rows))

    def test_i1_line_key_repeats_each_condition_and_invalid_condition_refuse_by_name(self):
        sellable = self.row()
        damaged = self.row(qty="2", cost="0.0000", condition="damaged_unsellable")
        for repeated in (sellable, damaged):
            with self.subTest(condition=repeated["condition"]):
                self.assert_refused(
                    [sellable, damaged, repeated],
                    rf"repeats \(sku, condition\): COUNT-A, {repeated['condition']}",
                )
        self.assert_refused([self.row(condition="seconds")],
                            "condition must be sellable or damaged_unsellable")

    def test_i2_damaged_cost_qty_and_missing_sellable_refuse_by_field_name(self):
        sellable = self.row()
        cases = (
            ([sellable, self.row(qty="2", cost="1.0000", condition="damaged_unsellable")],
             "damaged_unsellable agreed_unit_cost_twd must be exactly 0.0000"),
            ([self.row(qty="2", cost="0.0000", condition="damaged_unsellable")],
             "damaged_unsellable line for COUNT-A requires a sellable line for the same SKU"),
            ([sellable, self.row(qty="0", cost="0.0000", condition="damaged_unsellable")],
             "damaged_unsellable qty_pieces must be greater than zero"),
        )
        for rows, message in cases:
            with self.subTest(message=message):
                self.assert_refused(rows, message)

    def test_i2_every_active_sku_needs_sellable_line_but_explicit_zero_is_valid(self):
        Product.objects.create(sku="COUNT-B", name="Synthetic", uom="PC", pieces_per_sale_unit=1)
        self.assert_refused([self.row()], r"omits active SKU sellable line\(s\): COUNT-B")
        result = import_counts(self.source([self.row(), self.row(sku="COUNT-B", qty="0")]))
        self.assertEqual(result.parsed_rows, 2)

    def test_i4_posting_keeps_per_line_value_identity(self):
        payload = {"counted_at": "2026-10-04", "evidence_ref": "COUNT-R2",
                   "lines": [{"sku": "COUNT-A", "qty_pieces": "10",
                              "agreed_unit_cost_twd": "10.0000",
                              "line_value_twd": "99.0000", "condition": "sellable"}],
                   "damaged_lines": [], "total_value_twd": "99.0000"}
        event = LedgerEvent(event_type="inventory.opening_counted",
            entity_table="ops.stockcount", entity_id=1,
            occurred_at=datetime(2026, 10, 4, 12, tzinfo=TZ), payload=payload,
            idempotency_key="bad-line-value", source_filename="synthetic", dataset_kind="SAMPLE")
        with self.assertRaisesRegex(PostingError,
                                    "line_value_twd disagrees with quantity and cost"):
            plan(event)

    def test_i3_posting_refuses_damaged_rows_in_sellable_schedule(self):
        payload = {"counted_at": "2026-10-04", "evidence_ref": "COUNT-R2",
                   "lines": [{"sku": "COUNT-A", "qty_pieces": "2",
                              "agreed_unit_cost_twd": "0.0000",
                              "line_value_twd": "0.0000",
                              "condition": "damaged_unsellable"}],
                   "damaged_lines": [{"sku": "COUNT-A", "qty_pieces": 2}],
                   "total_value_twd": "0.0000"}
        event = LedgerEvent(event_type="inventory.opening_counted",
            entity_table="ops.stockcount", entity_id=1,
            occurred_at=datetime(2026, 10, 4, 12, tzinfo=TZ), payload=payload,
            idempotency_key="damaged-in-lines", source_filename="synthetic",
            dataset_kind="SAMPLE")
        with self.assertRaisesRegex(PostingError, "lines must be sellable"):
            plan(event)


class DamagedCountLifecycleTests(TestCase):
    def setUp(self):
        DatasetSettings.objects.update_or_create(pk=1, defaults={"dataset_kind": "SAMPLE"})
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.product = Product.objects.create(
            sku="TS-MN-006-P", name="Mixed count", uom="PC", pieces_per_sale_unit=12
        )

    def source(self, day, ref, sellable_qty, damaged_qty=2):
        path = Path(self.temp.name) / f"SAMPLE_count_{day}.csv"
        rows = [
            {"counted_at": day, "evidence_ref": ref, "sku": self.product.sku,
             "qty_pieces": str(sellable_qty), "agreed_unit_cost_twd": "10.0000",
             "condition": "sellable"},
            {"counted_at": day, "evidence_ref": ref, "sku": self.product.sku,
             "qty_pieces": str(damaged_qty), "agreed_unit_cost_twd": "0.0000",
             "condition": "damaged_unsellable"},
        ]
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=load_schema("counts")["header"])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def ledger(self, entry_id):
        return [(line.account_id, line.sku, line.qty_delta_pieces,
                 line.debit, line.credit)
                for line in JournalLine.objects.filter(entry_id=entry_id).order_by("id")]

    def add_two_sellable_pieces_at_wac(self):
        occurred_at = datetime(2026, 10, 4, 13, tzinfo=TZ)
        entry = JournalEntry.objects.create(occurred_at=occurred_at, period="2026-10",
            dataset_kind="SAMPLE", source_kind="ops", source_ref="ops:synthetic-receipt")
        JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="1231"),
            sku=self.product.sku, qty_delta_pieces=2, debit=D("20.0000"),
            source_ref=entry.source_ref)
        JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="2171"),
            credit=D("20.0000"), source_ref=entry.source_ref)
        InventoryMove.objects.create(product=self.product, kind="received", qty_delta_pieces=2,
            value_delta_twd=D("20.0000"), occurred_at=occurred_at,
            idempotency_key="synthetic-receipt-move", source_filename="synthetic",
            dataset_kind="SAMPLE")
        position = WacPosition.objects.get(pk=self.product.sku)
        position.qty_pieces += 2
        position.value_twd += D("20.0000")
        position.save(update_fields=["qty_pieces", "value_twd"])

    def test_i3_to_i7_opening_and_later_count_match_expected_ledgers_and_g3(self):
        opening_result = import_counts(self.source("2026-10-04", "COUNT-OPEN", 10), commit=True)
        self.assertEqual((opening_result.inserted_rows, opening_result.inserted_events), (4, 1))
        opening_event = LedgerEvent.objects.get(event_type="inventory.opening_counted")
        self.assertEqual(opening_event.payload["damaged_lines"],
                         [{"sku": self.product.sku, "qty_pieces": 2}])
        self.assertEqual(len(opening_event.payload["lines"]), 1)
        self.assertEqual(D(opening_event.payload["total_value_twd"]), D("100.0000"))
        self.assertEqual(StockCountLine.objects.filter(product=self.product).count(), 2)
        damaged = StockCountLine.objects.get(product=self.product,
                                             condition="damaged_unsellable")
        self.assertEqual((damaged.qty_pieces, damaged.agreed_unit_cost_twd,
                          damaged.line_value_twd), (2, D("0.0000"), D("0.0000")))
        self.assertEqual(list(InventoryMove.objects.values_list("qty_delta_pieces", flat=True)), [10])

        opening_entry = post_event(opening_event)
        self.assertEqual(self.ledger(opening_entry), [
            ("1231", self.product.sku, D("10.0000"), D("100.0000"), D("0.0000")),
            ("3111", None, None, D("0.0000"), D("100.0000")),
        ])
        self.assertFalse(JournalLine.objects.filter(entry_id=opening_entry,
                                                    account_id="5121").exists())
        self.assertEqual((OnHand.objects.get(pk=self.product.sku).qty_pieces,
                          WacPosition.objects.get(pk=self.product.sku).qty_pieces,
                          WacPosition.objects.get(pk=self.product.sku).value_twd),
                         (10, D("10.0000"), D("100.0000")))
        self.assertEqual(inventory_roll_forward("2026-11").rows[0]["identity"], "TIES")

        self.add_two_sellable_pieces_at_wac()
        later_result = import_counts(self.source("2026-10-05", "COUNT-LATER", 9), commit=True)
        self.assertEqual((later_result.inserted_rows, later_result.inserted_events), (4, 1))
        adjusted = LedgerEvent.objects.get(event_type="inventory.adjusted")
        self.assertEqual(adjusted.payload["damaged_lines"],
                         [{"sku": self.product.sku, "qty_pieces": 2}])
        self.assertEqual((D(adjusted.payload["qty_pieces"]),
                          D(adjusted.payload["source_value_twd"])),
                         (D("3.0000"), D("30.0000")))
        self.assertEqual(InventoryMove.objects.filter(kind="adjusted").count(), 1)
        self.assertEqual(InventoryMove.objects.get(kind="adjusted").qty_delta_pieces, -3)

        adjusted_entry = post_event(adjusted)
        self.assertEqual(self.ledger(adjusted_entry), [
            ("5121", self.product.sku, None, D("30.0000"), D("0.0000")),
            ("1231", self.product.sku, D("-3.0000"), D("0.0000"), D("30.0000")),
        ])
        self.assertEqual((OnHand.objects.get(pk=self.product.sku).qty_pieces,
                          WacPosition.objects.get(pk=self.product.sku).qty_pieces,
                          WacPosition.objects.get(pk=self.product.sku).value_twd),
                         (9, D("9.0000"), D("90.0000")))

        report = inventory_roll_forward("2026-11")
        self.assertEqual(report.rows[0]["identity"], "TIES")
        self.assertEqual(report.rows[-1]["identity"], "TIES")
        damaged_section = report.sections[1]
        self.assertEqual(damaged_section.title, "Damaged pieces held (latest count)")
        self.assertEqual((damaged_section.rows[0]["sku"],
                          damaged_section.rows[0]["pieces"].amount,
                          damaged_section.rows[0]["counted_at"],
                          damaged_section.rows[0]["evidence_ref"]),
                         (self.product.sku, D("2.0000"), "2026-10-05", "COUNT-LATER"))
        self.assertIn("Held pending the 記帳士. Do not destroy.", report.notes)

        user = get_user_model().objects.create_user(username="r2-reporter", password="synthetic")
        self.client.force_login(user)
        response = self.client.get("/reports/inventory/?period=2026-11&format=csv")
        rows = list(csv.reader(StringIO(response.content.decode())))
        self.assertIn(["section", "Damaged pieces held (latest count)"], rows)
        damaged_csv = rows[rows.index(["section", "Damaged pieces held (latest count)"]) + 2]
        self.assertEqual((damaged_csv[0], damaged_csv[1]), (self.product.sku, "2.0000"))

    def test_i6_upward_sellable_adjustment_remains_refused(self):
        import_counts(self.source("2026-10-04", "COUNT-OPEN", 10), commit=True)
        post_event(LedgerEvent.objects.get(event_type="inventory.opening_counted"))
        with self.assertRaisesRegex(ImportRefused,
                                    "implies an increase; a receipt is needed, not an adjustment"):
            import_counts(self.source("2026-10-05", "COUNT-UP", 11), commit=True)

    def test_damaged_csv_section_uses_absent_markers_when_latest_count_has_none(self):
        path = Path(self.temp.name) / "SAMPLE_count_2026-10-04.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=load_schema("counts")["header"])
            writer.writeheader()
            writer.writerow({"counted_at": "2026-10-04", "evidence_ref": "COUNT-CLEAN",
                             "sku": self.product.sku, "qty_pieces": "10",
                             "agreed_unit_cost_twd": "10.0000", "condition": "sellable"})
        import_counts(path, commit=True)
        report = inventory_roll_forward("2026-10")
        row = report.sections[1].rows[0]
        self.assertEqual((row["sku"], row["pieces"].amount,
                          row["pieces"].cost_basis, row["counted_at"], row["evidence_ref"]),
                         ("ABSENT", None, "absent", "ABSENT", "ABSENT"))
