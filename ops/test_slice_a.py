"""Slice A checks. Public CI failures must name IDs/counts, never customer rows."""

from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
import csv
import tempfile
from decimal import Decimal

from django.db import DatabaseError, IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from core.models import DatasetSettings
from ops.etsy_import import (ImportRefused, ImportResult, _orders, _read_csv,
                             _minor, _statement, emit_event, import_etsy, quarantine_file)
from ops.models import (Channel, LedgerEvent, Order, OrderLine, Product,
                        EtsyStatementRow, InventoryMove, OnHand, Shipment,
                        OpsPeriod, OPS_EVENT_TYPES)
from ops.transitions import record_order_exception, record_settlement_reversal


class FilenameQuarantineTests(SimpleTestCase):
    def test_sample_refused_when_application_is_actual(self):
        with self.assertRaisesRegex(ImportRefused, "SAMPLE.*ACTUAL"):
            quarantine_file("SAMPLE_etsy_orderitems_2025-12.csv", "ACTUAL")

    def test_actual_refused_when_application_is_sample(self):
        with self.assertRaisesRegex(ImportRefused, "ACTUAL.*SAMPLE"):
            quarantine_file("etsy_orderitems_2025-12.csv", "SAMPLE")

    def test_unknown_filename_refused(self):
        with self.assertRaisesRegex(ImportRefused, "orders.csv"):
            quarantine_file("orders.csv", "SAMPLE")

    def test_matching_names_are_allowed(self):
        self.assertEqual(quarantine_file("SAMPLE_etsy_statement_2025-12.csv", "SAMPLE"), "SAMPLE")
        self.assertEqual(quarantine_file("etsy_statement_2025-12.csv", "ACTUAL"), "ACTUAL")


class ImportControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Channel.objects.create(code="etsy", name="Etsy")
        for sku in ("TS-FL-001-S", "TS-HN-007-M", "TS-SL-003-L", "TS-FS-004-P"):
            Product.objects.create(sku=sku, name=sku, uom="PK")
            InventoryMove.objects.create(
                product_id=sku, kind="opening", qty_delta_packs=100,
                occurred_at=datetime(2025, 12, 1, tzinfo=ZoneInfo("Asia/Taipei")),
                idempotency_key=f"opening|{sku}", source_filename="SAMPLE_count",
                dataset_kind="SAMPLE",
            )

    def paths(self):
        base = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
        return (base / "SAMPLE_etsy_orderitems_2025-12_fixture.csv",
                base / "SAMPLE_etsy_statement_2025-12_fixture.csv")

    def test_fixture_contains_no_customer_fields(self):
        order_path, statement_path = self.paths()
        rows = _read_csv(order_path, "orderitems")
        private = ("Buyer", "Ship Name", "Ship Address1", "Ship Address2",
                   "Ship City", "Ship State", "Ship Zipcode")
        self.assertTrue(all(not row[column] for row in rows for column in private))
        self.assertTrue(all(not row["Title"] for row in _read_csv(statement_path, "statement")))

    def make_order(self, order_id="synthetic", status="placed"):
        return Order.objects.create(
            channel=Channel.objects.get(code="etsy"), channel_order_id=order_id,
            order_date=datetime(2025, 12, 3).date(), currency="USD", discount_funded_by="none",
            gross_minor=100, discount_minor=0, buyer_paid_minor=100,
            shipping_minor=0, shipping_discount_minor=0, dest_country="US", status=status,
            source_filename="SAMPLE_test", dataset_kind="SAMPLE",
        )

    def test_commit_refused_while_fixture_unverified(self):
        with self.assertRaisesRegex(ImportRefused, "unverified"):
            import_etsy(*self.paths(), commit=True)
        self.assertEqual(Order.objects.count(), 0)

    def test_missing_founder_coupon_mapping_refuses_commit(self):
        from ops.etsy_import import load_schema

        def verified(kind):
            data = load_schema(kind)
            data["verified"] = True
            return data

        with patch("ops.etsy_import.load_schema", side_effect=verified):
            with self.assertRaisesRegex(ImportRefused, "founder funder mapping"):
                import_etsy(*self.paths(), commit=True)
        self.assertEqual(Order.objects.count(), 0)

    def test_reimport_same_files_inserts_zero_rows_and_events(self):
        # This patch changes only the in-memory test fixture; shipped JSON remains unverified.
        from ops.etsy_import import load_schema

        def verified(kind):
            result = load_schema(kind)
            result["verified"] = True
            return result

        with patch("ops.etsy_import.load_schema", side_effect=verified):
            first = import_etsy(*self.paths(), commit=True, coupon_funding={
                "WELCOME10": "seller", "HOLIDAY15": "seller", "FREESHIP": "seller"
            })
            counts = (Order.objects.count(), OrderLine.objects.count(),
                      EtsyStatementRow.objects.count(), LedgerEvent.objects.count())
            second = import_etsy(*self.paths(), commit=True, coupon_funding={
                "WELCOME10": "seller", "HOLIDAY15": "seller", "FREESHIP": "seller"
            })
        self.assertGreater(first.inserted_rows, 0)
        placed = LedgerEvent.objects.get(idempotency_key="order.placed|etsy|2918473019")
        self.assertEqual((placed.amount_minor, placed.payload["discount"]), (3097, 260))
        self.assertEqual(LedgerEvent.objects.get(event_type="settlement.received").amount_minor, 5186)
        listing = LedgerEvent.objects.get(event_type="cost.recorded")
        self.assertEqual((listing.payload["category"], listing.payload["settled_via"]),
                         ("platform_listing_fee", "etsy_rail"))
        self.assertEqual(second.inserted_rows, 0)
        self.assertEqual(second.inserted_events, 0)
        self.assertEqual(counts, (Order.objects.count(), OrderLine.objects.count(),
                                  EtsyStatementRow.objects.count(), LedgerEvent.objects.count()))

    def test_changed_statement_period_is_refused_without_partial_insert(self):
        from ops.etsy_import import load_schema

        def verified(kind):
            data = load_schema(kind)
            data["verified"] = True
            return data

        orders, statement = self.paths()
        funding = {"WELCOME10": "seller", "HOLIDAY15": "seller", "FREESHIP": "seller"}
        with patch("ops.etsy_import.load_schema", side_effect=verified):
            import_etsy(orders, statement, commit=True, coupon_funding=funding)
            before = (EtsyStatementRow.objects.count(), LedgerEvent.objects.count())
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tests") as directory:
                altered = Path(directory) / statement.name
                with statement.open(newline="", encoding="utf-8-sig") as stream:
                    rows = list(csv.DictReader(stream))
                    headers = list(rows[0])
                rows[1]["Fees & Taxes"] = rows[1]["Net"] = "-2.02"
                with altered.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=headers)
                    writer.writeheader()
                    writer.writerows(rows)
                with self.assertRaisesRegex(ImportRefused, "multiset changed"):
                    import_etsy(orders, altered, commit=True, coupon_funding=funding)
        self.assertEqual(before, (EtsyStatementRow.objects.count(), LedgerEvent.objects.count()))

    def test_changed_existing_order_line_is_refused(self):
        from ops.etsy_import import load_schema

        def verified(kind):
            data = load_schema(kind)
            data["verified"] = True
            return data

        orders, statement = self.paths()
        funding = {"WELCOME10": "seller", "HOLIDAY15": "seller", "FREESHIP": "seller"}
        with patch("ops.etsy_import.load_schema", side_effect=verified):
            import_etsy(orders, statement, commit=True, coupon_funding=funding)
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tests") as directory:
                altered = Path(directory) / orders.name
                with orders.open(newline="", encoding="utf-8-sig") as stream:
                    rows = list(csv.DictReader(stream))
                    headers = list(rows[0])
                rows[0]["SKU"] = "TS-HN-007-M"
                with altered.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=headers)
                    writer.writeheader()
                    writer.writerows(rows)
                with self.assertRaisesRegex(ImportRefused, "Previously imported order"):
                    import_etsy(altered, statement, commit=True, coupon_funding=funding)

    def test_header_mismatch_refused_before_rows_are_parsed(self):
        order_path, statement_path = self.paths()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tests") as directory:
            altered = Path(directory) / order_path.name
            with order_path.open(newline="", encoding="utf-8-sig") as stream:
                rows = list(csv.reader(stream))
            rows[0][0] = "Renamed Sale Date"
            with altered.open("w", newline="", encoding="utf-8") as stream:
                csv.writer(stream).writerows(rows)
            with self.assertRaisesRegex(ImportRefused, "Header mismatch"):
                import_etsy(altered, statement_path)
        self.assertEqual(Order.objects.count(), 0)

    def test_gross_basis_asymmetric_on_discounted_sample_order(self):
        order_path, statement_path = self.paths()
        parsed = _orders(_read_csv(order_path, "orderitems"),
                         {"WELCOME10": "seller", "HOLIDAY15": "seller", "FREESHIP": "seller"},
                         ImportResult())
        with statement_path.open(newline="", encoding="utf-8-sig") as stream:
            sales = {row["Info"].split("#")[-1]: int(Decimal(row["Amount"]) * 100)
                     for row in csv.DictReader(stream) if row["Type"] == "Sale"}
        discounted = parsed["2918473019"]
        plain = parsed["2918473022"]
        self.assertEqual((discounted["gross"], discounted["buyer_paid"], sales["2918473019"]),
                         (3097, 2837, 3097))
        self.assertNotEqual(discounted["buyer_paid"], sales["2918473019"])
        self.assertEqual((plain["gross"], plain["buyer_paid"], sales["2918473022"]),
                         (3149, 3149, 3149))

    def test_on_hand_is_view_over_signed_pack_movements(self):
        sku = "TS-HN-007-M"
        InventoryMove.objects.create(
            product_id=sku, kind="sold", qty_delta_packs=-3,
            occurred_at=datetime(2025, 12, 2, tzinfo=ZoneInfo("Asia/Taipei")),
            idempotency_key="sold|synthetic", source_filename="SAMPLE_test", dataset_kind="SAMPLE",
        )
        InventoryMove.objects.create(
            product_id=sku, kind="received", qty_delta_packs=2,
            occurred_at=datetime(2025, 12, 3, tzinfo=ZoneInfo("Asia/Taipei")),
            idempotency_key="received|synthetic", source_filename="SAMPLE_test", dataset_kind="SAMPLE",
        )
        self.assertEqual(OnHand.objects.get(sku=sku).qty_packs, 100 - 3 + 2)
        self.assertFalse(any(f.name in {"on_hand", "quantity_on_hand"} for f in Product._meta.fields))

    def test_revenue_emission_requires_ship_date_even_for_direct_sql(self):
        order = self.make_order("synthetic-no-ship")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Shipment.objects.create(order=order, status="dispatched", ship_date=None,
                                        source_filename="SAMPLE_test", dataset_kind="SAMPLE")
        with self.assertRaisesRegex(ImportRefused, "ship_date"):
            emit_event(event_type="order.shipped", entity_table="ops.order", entity_id=order.pk,
                       occurred_at=datetime(2025, 12, 3, tzinfo=ZoneInfo("Asia/Taipei")),
                       idempotency_key="ship|synthetic", source_filename="SAMPLE_test",
                       dataset_kind="SAMPLE", amount_minor=100, currency="USD")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                LedgerEvent.objects.create(
                    event_type="order.shipped", entity_table="ops.order", entity_id=order.pk,
                    occurred_at=datetime(2025, 12, 3, tzinfo=ZoneInfo("Asia/Taipei")),
                    idempotency_key="direct-ship-without-date", source_filename="SAMPLE_test",
                    dataset_kind="SAMPLE", amount_minor=100, currency="USD",
                )
        self.assertEqual(LedgerEvent.objects.count(), 0)

    def test_synthetic_domestic_and_multiline_order(self):
        order_path, _ = self.paths()
        rows = _read_csv(order_path, "orderitems")
        first = rows[0].copy()
        second = first.copy()
        second["Order ID"] = first["Order ID"]
        first["Ship Country"] = second["Ship Country"] = "Taiwan"
        # Use a numeric transaction ID as Etsy does.
        second["Transaction ID"] = "9999999999"
        parsed = _orders([first, second], {"WELCOME10": "seller"}, ImportResult())
        self.assertEqual(len(parsed[first["Order ID"]]["lines"]), 2)
        self.assertEqual(parsed[first["Order ID"]]["country"], "TW")

    def test_tax_is_removed_from_gross_and_null_sentinel_stays_null(self):
        order_path, _ = self.paths()
        row = _read_csv(order_path, "orderitems")[1].copy()
        row["Order Sales Tax"] = "1.25"
        order = _orders([row], {}, ImportResult())[row["Order ID"]]
        self.assertEqual((order["gross"], order["tax"]), (3149, 125))
        self.assertIsNone(_minor("--", nullable=True))
        with self.assertRaises(ImportRefused):
            _minor("--")

    def test_fee_without_sale_is_named_reconciling_item(self):
        result = import_etsy(*self.paths())
        self.assertTrue(any("2918473050" in item and "without Sale" in item
                            for item in result.reconciling_items))
        self.assertEqual((result.parsed_order_rows, result.parsed_statement_rows), (5, 10))

    def test_historical_order_without_sale_blocks_after_sixty_days(self):
        older = self.make_order("historical-no-sale")
        older.order_date = datetime(2025, 10, 1).date()
        older.save(update_fields=["order_date"])
        result = import_etsy(*self.paths())
        self.assertTrue(any("historical-no-sale" in item and "no Sale" in item
                            for item in result.blockers))

    def test_positive_deposit_needs_reversal_evidence(self):
        orders_path, statement_path = self.paths()
        orders = _orders(_read_csv(orders_path, "orderitems"),
                         {"WELCOME10": "seller", "HOLIDAY15": "seller", "FREESHIP": "seller"},
                         ImportResult())
        rows = _read_csv(statement_path, "statement")
        rows[-1]["Amount"] = rows[-1]["Net"] = "51.86"
        result = ImportResult()
        _statement(rows, "2025-12", orders, result)
        self.assertTrue(any("payout reversal" in item for item in result.blockers))

    def test_database_rejects_wrong_movement_sign(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InventoryMove.objects.create(
                    product_id="TS-HN-007-M", kind="sold", qty_delta_packs=1,
                    occurred_at=datetime(2025, 12, 3, tzinfo=ZoneInfo("Asia/Taipei")),
                    idempotency_key="bad-sign", source_filename="SAMPLE_test", dataset_kind="SAMPLE",
                )

    def test_database_rejects_unknown_discount_funder(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Order.objects.create(
                    channel=Channel.objects.get(code="etsy"), channel_order_id="bad-funder",
                    order_date=datetime(2025, 12, 3).date(), currency="USD",
                    discount_funded_by="none", gross_minor=100, discount_minor=10,
                    buyer_paid_minor=90, shipping_minor=0, shipping_discount_minor=0,
                    dest_country="US", source_filename="SAMPLE_test", dataset_kind="SAMPLE",
                )

    def test_closed_ops_period_rejects_new_event_at_database(self):
        OpsPeriod.objects.create(period="2025-12", status="CLOSED")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                emit_event(event_type="inventory.adjusted", entity_table="ops.inventorymove",
                           entity_id=1, occurred_at=datetime(2025, 12, 3, tzinfo=ZoneInfo("Asia/Taipei")),
                           idempotency_key="closed-period", source_filename="SAMPLE_test",
                           dataset_kind="SAMPLE")
        self.assertEqual(LedgerEvent.objects.count(), 0)

    def test_synthetic_cancel_refund_and_reversal_paths_require_evidence(self):
        when = datetime(2025, 12, 3, tzinfo=ZoneInfo("Asia/Taipei"))
        cancel = self.make_order("cancel")
        with self.assertRaises(ImportRefused):
            record_order_exception(order=cancel, event_type="order.cancelled", evidence_ref="",
                                   occurred_at=when, amount_minor=100, was_paid=True)
        self.assertTrue(record_order_exception(order=cancel, event_type="order.cancelled",
                                               evidence_ref="synthetic-cancel", occurred_at=when,
                                               amount_minor=100, was_paid=True))
        refund = self.make_order("refund", status="shipped")
        with self.assertRaises(ImportRefused):
            record_order_exception(order=refund, event_type="order.refunded",
                                   evidence_ref="synthetic-refund", occurred_at=when, amount_minor=100)
        Shipment.objects.create(order=refund, status="dispatched", ship_date=when.date(),
                                source_filename="SAMPLE_test", dataset_kind="SAMPLE")
        self.assertTrue(record_order_exception(order=refund, event_type="order.refunded",
                                               evidence_ref="synthetic-refund", occurred_at=when,
                                               amount_minor=100))
        from ops.models import EtsyStatementPeriod
        period = EtsyStatementPeriod.objects.create(period="2025-12", multiset_digest="synthetic",
                                                    source_sha256="synthetic",
                                                    row_count=1, source_filename="SAMPLE_test",
                                                    dataset_kind="SAMPLE")
        deposit = EtsyStatementRow.objects.create(period=period, row_key="synthetic-deposit",
                                                 row_type="Deposit", occurred_at=when,
                                                 currency="USD", amount_minor=-100, net_minor=-100,
                                                 source_filename="SAMPLE_test", dataset_kind="SAMPLE")
        with self.assertRaises(ImportRefused):
            record_settlement_reversal(original_deposit=deposit, evidence_ref="",
                                       occurred_at=when, amount_minor=100)
        self.assertTrue(record_settlement_reversal(original_deposit=deposit,
                                                   evidence_ref="synthetic-bank-reversal",
                                                   occurred_at=when, amount_minor=100))
        self.assertEqual(LedgerEvent.objects.count(), 3)

    def test_all_22_ops_catalogue_types_are_emittable_without_posting(self):
        when = datetime(2025, 12, 3, tzinfo=ZoneInfo("Asia/Taipei"))
        order = self.make_order("event-matrix", status="shipped")
        Shipment.objects.create(order=order, status="dispatched", ship_date=when.date(),
                                source_filename="SAMPLE_test", dataset_kind="SAMPLE")
        for index, event_type in enumerate(OPS_EVENT_TYPES):
            payload = {"evidence_ref": "synthetic-evidence", "discount_funded_by": "none"}
            self.assertTrue(emit_event(
                event_type=event_type, entity_table="ops.order", entity_id=order.pk,
                occurred_at=when, idempotency_key=f"synthetic-event-{index}",
                source_filename="SAMPLE_test", dataset_kind="SAMPLE",
                amount_minor=100, currency="USD", payload=payload,
            ))
        self.assertEqual(LedgerEvent.objects.count(), 22)
        self.assertEqual(LedgerEvent.objects.exclude(posted_entry_id__isnull=True).count(), 0)
