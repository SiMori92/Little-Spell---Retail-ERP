"""Synthetic intake tests assert IDs and counts; no customer row is printed on failure."""

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.apps import apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from acct.posting import post_event
from ops.file_intake import import_counts, import_receipts, load_schema
from ops.intake import ImportRefused
from ops.models import InventoryMove, LedgerEvent, Product, Receipt, StockCount, StockCountLine


class FileIntakeTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for sku in ("SYN-A", "SYN-B"):
            Product.objects.create(sku=sku, name="Synthetic", uom="PK")

    def source(self, kind, filename, rows, *, columns=None):
        fixture = load_schema(kind)
        path = Path(self.temp.name) / filename
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns or fixture["header"])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def verified(self):
        original = load_schema
        return patch("ops.file_intake.load_schema", side_effect=lambda kind: {**original(kind), "verified": True})

    def count_rows(self, *, date="2025-03-27", ref="COUNT-ONE", first="3", second="0"):
        return [
            {"counted_at": date, "evidence_ref": ref, "sku": "SYN-A", "qty_packs": first,
             "agreed_unit_cost_twd": "12.50", "condition": "sellable"},
            {"counted_at": date, "evidence_ref": ref, "sku": "SYN-B", "qty_packs": second,
             "agreed_unit_cost_twd": "5.00", "condition": "damaged_unsellable"},
        ]

    def receipt_row(self, **changes):
        row = {"occurred_on": "2025-03-27", "category": "rent", "amount_twd": "50.00",
               "settled_via": "payable", "evidence_ref": "DOC-ONE", "description": "Synthetic rent"}
        row.update(changes)
        return row

    def test_unclassified_names_and_unverified_fixtures_refuse_every_kind(self):
        paths = (
            ("counts", self.source("counts", "mystery.csv", self.count_rows()), import_counts),
            ("receipts", self.source("receipts", "wrong.csv", [self.receipt_row()]), import_receipts),
        )
        for kind, path, intake in paths:
            with self.subTest(kind=kind), self.assertRaisesRegex(ImportRefused, "Unclassified"):
                intake(path)
        count = self.source("counts", "SAMPLE_count.csv", self.count_rows())
        receipt = self.source("receipts", "SAMPLE_receipts.csv", [self.receipt_row()])
        for kind, path, intake in (("counts", count, import_counts),
                                   ("receipts", receipt, import_receipts)):
            with self.subTest(kind=kind), self.assertRaisesRegex(ImportRefused, "schema fixture is unverified"):
                intake(path, commit=True)

    def test_receipt_refusals_are_postable_rule_boundaries(self):
        cases = (
            ({"category": "advertising"}, "channel_attribution"),
            ({"settled_via": "etsy_rail"}, "payable or bank"),
            ({"evidence_ref": ""}, "evidence_ref is mandatory"),
            ({"category": "platform_listing_fee"}, "platform_listing_fee belongs"),
        )
        for changed, error in cases:
            with self.subTest(error=error):
                path = self.source("receipts", "SAMPLE_receipts.csv", [self.receipt_row(**changed)])
                with self.assertRaisesRegex(ImportRefused, error):
                    import_receipts(path)

    def test_receipt_reimport_inserts_nothing_and_keeps_natural_key(self):
        path = self.source("receipts", "SAMPLE_receipts.csv", [self.receipt_row()])
        with self.verified():
            first = import_receipts(path, commit=True)
            second = import_receipts(path, commit=True)
        self.assertEqual((first.inserted_rows, first.inserted_events), (1, 1))
        self.assertEqual((second.inserted_rows, second.inserted_events), (0, 0))
        self.assertEqual(Receipt.objects.count(), 1)
        self.assertEqual(LedgerEvent.objects.filter(event_type="cost.recorded").count(), 1)

    def test_count_requires_every_sku_with_explicit_zero_and_reimports_cleanly(self):
        missing = self.source("counts", "SAMPLE_count.csv", self.count_rows()[:1])
        with self.assertRaisesRegex(ImportRefused, "omits active SKU.*SYN-B"):
            import_counts(missing)
        path = self.source("counts", "SAMPLE_count.csv", self.count_rows())
        with self.verified():
            first = import_counts(path, commit=True)
            second = import_counts(path, commit=True)
        self.assertEqual((first.inserted_rows, first.inserted_events), (5, 1))
        self.assertEqual((second.inserted_rows, second.inserted_events), (0, 0))
        self.assertEqual(StockCountLine.objects.get(product_id="SYN-B").qty_packs, 0)
        self.assertEqual(InventoryMove.objects.get(product_id="SYN-B").qty_delta_packs, 0)

    def test_upward_adjustment_names_receipt_route_and_downward_emits_one_event(self):
        opening_path = self.source("counts", "SAMPLE_opening.csv", self.count_rows())
        with self.verified():
            import_counts(opening_path, commit=True)
            post_event(LedgerEvent.objects.get(event_type="inventory.opening_counted"))
            upward = self.source("counts", "SAMPLE_up.csv", self.count_rows(
                date="2025-03-28", ref="COUNT-UP", first="4"))
            with self.assertRaisesRegex(ImportRefused, "a receipt is needed"):
                import_counts(upward, commit=True)
            downward = self.source("counts", "SAMPLE_down.csv", self.count_rows(
                date="2025-03-28", ref="COUNT-DOWN", first="2"))
            first = import_counts(downward, commit=True)
            second = import_counts(downward, commit=True)
        self.assertEqual((first.inserted_events, second.inserted_events), (1, 0))
        self.assertEqual(StockCount.objects.count(), 2)
        self.assertEqual(LedgerEvent.objects.filter(event_type="inventory.adjusted").count(), 1)


class ReadOnlyAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="slice-f-reviewer", password="synthetic-test-password"
        )

    def test_every_ops_and_acct_model_is_registered_without_write_permission(self):
        self.client.force_login(self.user)
        request = self.client.get(reverse("admin:index")).wsgi_request
        for label in ("ops", "acct"):
            for model in apps.get_app_config(label).get_models():
                with self.subTest(model=model._meta.label):
                    model_admin = admin.site._registry[model]
                    self.assertFalse(model_admin.has_add_permission(request))
                    self.assertFalse(model_admin.has_change_permission(request))
                    self.assertFalse(model_admin.has_delete_permission(request))
                    add_url = reverse(f"admin:{label}_{model._meta.model_name}_add")
                    self.assertIn(self.client.post(add_url).status_code, (403, 404))

    def test_existing_row_change_is_refused(self):
        self.client.force_login(self.user)
        product = Product.objects.create(sku="ADMIN-SKU", name="Synthetic", uom="PK")
        response = self.client.post(reverse("admin:ops_product_change", args=[product.pk]),
                                    {"sku": "CHANGED", "name": "Synthetic", "uom": "PK"})
        self.assertEqual(response.status_code, 403)
        product.refresh_from_db()
        self.assertEqual(product.sku, "ADMIN-SKU")
