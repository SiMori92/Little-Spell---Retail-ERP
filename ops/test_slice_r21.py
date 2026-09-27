"""Slice R-2.1: packaging stock-count value lives on 1233, never on 1231 or in sellable WAC."""

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum
from django.test import TestCase

from acct.gates import g3
from acct.models import JournalEntry, JournalLine, WacPosition
from acct.posting import PostingError, plan, post_event
from core.models import DatasetSettings
from ops.file_intake import import_counts, load_schema
from ops.models import NOT_APPLICABLE, InventoryMove, LedgerEvent, OnHand, Product


D = Decimal
TZ = ZoneInfo("Asia/Taipei")
PKG = "PKG-MAIL-LS"
SKU = "TS-MN-006-P"


class PackagingCountTests(TestCase):
    def setUp(self):
        DatasetSettings.objects.update_or_create(pk=1, defaults={"dataset_kind": "SAMPLE"})
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        Product.objects.create(sku=PKG, name="Mailer", uom="PC", pieces_per_sale_unit=1,
                               product_type="packaging", ingredient_ref=NOT_APPLICABLE)
        Product.objects.create(sku=SKU, name="Sticker", uom="PC", pieces_per_sale_unit=12)

    def source(self, day, ref, pkg_qty, sku_qty=10, damaged=()):
        path = Path(self.temp.name) / f"SAMPLE_count_{day}.csv"
        rows = [(PKG, pkg_qty, "7.0000", "sellable"), (SKU, sku_qty, "10.0000", "sellable")]
        rows += [(sku, qty, "0.0000", "damaged_unsellable") for sku, qty in damaged]
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=load_schema("counts")["header"])
            writer.writeheader()
            for sku, qty, cost, condition in rows:
                writer.writerow({"counted_at": day, "evidence_ref": ref, "sku": sku,
                                 "qty_pieces": str(qty), "agreed_unit_cost_twd": cost,
                                 "condition": condition})
        return path

    def open_books(self, damaged=()):
        import_counts(self.source("2026-10-04", "COUNT-OPEN", 1000, damaged=damaged), commit=True)
        event = LedgerEvent.objects.get(event_type="inventory.opening_counted")
        return event, post_event(event)

    def later_count(self, pkg_qty, damaged=()):
        import_counts(self.source("2026-10-05", "COUNT-LATER", pkg_qty, damaged=damaged), commit=True)
        event = LedgerEvent.objects.get(event_type="inventory.adjusted")
        return event, post_event(event)

    def ledger(self, entry_id):
        return [(line.account_id, line.sku, line.qty_delta_pieces, line.debit, line.credit)
                for line in JournalLine.objects.filter(entry_id=entry_id).order_by("id")]

    def totals(self, entry_id):
        lines = JournalLine.objects.filter(entry_id=entry_id)
        return {account: (sum((x.debit for x in lines if x.account_id == account), D(0)),
                          sum((x.credit for x in lines if x.account_id == account), D(0)))
                for account in sorted({x.account_id for x in lines})}

    def assert_sellable_wac_untouched(self):
        position = WacPosition.objects.get(pk=SKU)
        self.assertEqual((position.qty_pieces, position.value_twd), (D("10.0000"), D("100.0000")))
        self.assertFalse(WacPosition.objects.filter(pk=PKG).exists())

    def assert_g3_passes(self, pkg_pieces, pkg_value):
        result = g3("2026-11")
        self.assertEqual(result.status, "PASS", result.reason)
        rows = {row["sku"]: row for row in result.details["rows"]}
        self.assertEqual((D(rows[PKG]["ops_pieces"]), D(rows[PKG]["gl_pieces"]),
                          D(rows[PKG]["ops_twd"]), D(rows[PKG]["gl_twd"])),
                         (D(pkg_pieces), D(pkg_pieces), D(pkg_value), D(pkg_value)))
        self.assertGreater(D(rows[PKG]["gl_twd"]), 0)
        # G-3 nets 1231+1232+1233, so it would tie on 1231 too: the value must be on 1233.
        on_1233 = JournalLine.objects.filter(account_id="1233", sku=PKG).aggregate(
            qty=Sum("qty_delta_pieces"), debit=Sum("debit"), credit=Sum("credit"))
        self.assertEqual((on_1233["qty"] or D(0), (on_1233["debit"] or D(0)) - (on_1233["credit"] or D(0))),
                         (D(pkg_pieces), D(pkg_value)))
        self.assertFalse(JournalLine.objects.filter(account_id="1231", sku=PKG).exists())

    def test_i1_opening_count_debits_1233_for_packaging_and_1231_for_sellable(self):
        event, entry = self.open_books()
        self.assertEqual({row["sku"]: row["inventory_account"] for row in event.payload["lines"]},
                         {PKG: "1233", SKU: "1231"})
        self.assertEqual(self.ledger(entry), [
            ("1233", PKG, D("1000.0000"), D("7000.0000"), D("0.0000")),
            ("3111", None, None, D("0.0000"), D("7000.0000")),
            ("1231", SKU, D("10.0000"), D("100.0000"), D("0.0000")),
            ("3111", None, None, D("0.0000"), D("100.0000")),
        ])
        self.assertEqual(self.totals(entry), {
            "1231": (D("100.0000"), D("0.0000")),
            "1233": (D("7000.0000"), D("0.0000")),
            "3111": (D("0.0000"), D("7100.0000")),
        })

    def test_i1_payload_inventory_account_disagreeing_with_product_type_refuses(self):
        event, _ = self.open_books()
        payload = {**event.payload, "lines": [{**row, "inventory_account": "1231"}
                                              for row in event.payload["lines"]]}
        forged = LedgerEvent(event_type="inventory.opening_counted", entity_table="ops.stockcount",
            entity_id=1, occurred_at=event.occurred_at, payload=payload, idempotency_key="forged",
            source_filename="synthetic", dataset_kind="ACTUAL")
        with self.assertRaisesRegex(PostingError, f"opening count {PKG} inventory_account 1231 "
                                                  "disagrees with product_type, which posts to 1233"):
            plan(forged)

    def test_i3_packaging_never_enters_sellable_wac(self):
        self.open_books()
        self.assert_sellable_wac_untouched()
        self.later_count(990)
        self.assert_sellable_wac_untouched()

    def test_i2_later_packaging_shortfall_posts_5121_against_1233(self):
        self.open_books()
        event, entry = self.later_count(990)
        self.assertEqual(event.payload["sku"], PKG)
        self.assertEqual(event.payload["inventory_account"], "1233")
        self.assertEqual((D(event.payload["qty_pieces"]), D(event.payload["source_value_twd"])),
                         (D("10"), D("70.0000")))
        self.assertEqual(self.ledger(entry), [
            ("5121", PKG, None, D("70.0000"), D("0.0000")),
            ("1233", PKG, D("-10.0000"), D("0.0000"), D("70.0000")),
        ])
        self.assertFalse(JournalLine.objects.filter(entry_id=entry, account_id="1231").exists())
        self.assertEqual(OnHand.objects.get(pk=PKG).qty_pieces, 990)
        book = JournalLine.objects.filter(account_id="1233", sku=PKG).aggregate(
            qty=Sum("qty_delta_pieces"), debit=Sum("debit"), credit=Sum("credit"))
        self.assertEqual((book["qty"], book["debit"] - book["credit"]),
                         (D("990.0000"), D("6930.0000")))

    def test_i2_sellable_shortfall_stays_on_1231_and_records_its_account(self):
        self.open_books()
        import_counts(self.source("2026-10-05", "COUNT-LATER", 1000, sku_qty=7), commit=True)
        event = LedgerEvent.objects.get(event_type="inventory.adjusted")
        self.assertEqual(event.payload["inventory_account"], "1231")
        self.assertEqual(self.ledger(post_event(event)), [
            ("5121", SKU, None, D("30.0000"), D("0.0000")),
            ("1231", SKU, D("-3.0000"), D("0.0000"), D("30.0000")),
        ])

    def test_i2_disagreeing_or_missing_inventory_account_is_a_posting_error(self):
        self.open_books()
        cases = (
            ({"sku": PKG, "inventory_account": "1231"},
             f"inventory_account 1231 disagrees with product_type of {PKG}, which posts to 1233"),
            ({"sku": SKU, "inventory_account": "1233"},
             f"inventory_account 1233 disagrees with product_type of {SKU}, which posts to 1231"),
            ({"sku": PKG}, "inventory_account is required"),
        )
        for number, (fields, message) in enumerate(cases):
            with self.subTest(message=message):
                event = LedgerEvent.objects.create(event_type="inventory.adjusted",
                    entity_table="ops.stockcountline", entity_id=number + 1,
                    occurred_at=datetime(2026, 10, 5, 12, tzinfo=TZ),
                    payload={"evidence_ref": "COUNT-FORGED", "qty_pieces": "1", **fields},
                    idempotency_key=f"forged-adjustment-{number}", source_filename="synthetic",
                    dataset_kind="SAMPLE")
                entries = JournalEntry.objects.count()
                with self.assertRaisesRegex(CommandError, message):
                    call_command("post_accounting_event", "ops", str(event.pk))
                event.refresh_from_db()
                self.assertRegex(event.posting_error, message)
                self.assertIsNone(event.posted_entry_id)
                self.assertEqual(event.payload.get("inventory_account"), fields.get("inventory_account"))
                self.assertEqual(JournalEntry.objects.count(), entries)

    def test_i4_g3_ties_with_packaging_on_1233_after_opening_and_adjustment(self):
        self.open_books()
        self.assert_g3_passes("1000", "7000.0000")
        self.later_count(990)
        self.assert_g3_passes("990", "6930.0000")

    def test_i5_damaged_packaging_is_a_zero_value_memo_as_for_sellable(self):
        event, entry = self.open_books(damaged=((PKG, 5),))
        self.assertEqual(event.payload["damaged_lines"], [{"sku": PKG, "qty_pieces": 5}])
        self.assertEqual(D(event.payload["total_value_twd"]), D("7100.0000"))
        self.assertEqual(list(InventoryMove.objects.filter(product_id=PKG)
                              .values_list("qty_delta_pieces", flat=True)), [1000])
        self.assertEqual(self.totals(entry)["1233"], (D("7000.0000"), D("0.0000")))
        adjusted, adjusted_entry = self.later_count(990, damaged=((PKG, 10),))
        self.assertEqual(adjusted.payload["damaged_lines"], [{"sku": PKG, "qty_pieces": 10}])
        # The damaged pieces sit inside the 1233 shortfall at book cost, never as a second line.
        self.assertEqual(self.ledger(adjusted_entry), [
            ("5121", PKG, None, D("70.0000"), D("0.0000")),
            ("1233", PKG, D("-10.0000"), D("0.0000"), D("70.0000")),
        ])
        self.assertEqual(OnHand.objects.get(pk=PKG).qty_pieces, 990)
        self.assert_sellable_wac_untouched()
