"""Slice G-0 tests use synthetic reference data and never print customer data."""

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib import admin
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from acct.models import JournalLine
from core.models import DatasetSettings
from ops.compliance import PoBlocked, assert_po_eligible
from ops.file_intake import import_products, import_suppliers, load_schema, manifest
from ops.intake import ImportRefused
from ops.models import (LedgerEvent, Product, ProductComplianceChange, Supplier,
                        SupplierChange)


SAMPLES = Path(__file__).resolve().parents[1] / "docs" / "samples"


class SliceG0Tests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        DatasetSettings.objects.get_or_create(pk=1, defaults={"dataset_kind": "SAMPLE"})

    def source(self, kind, filename, rows):
        path = Path(self.temp.name) / filename
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=load_schema(kind)["header"])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def rows(self, kind):
        with (SAMPLES / f"SAMPLE_{kind}_2026-09-27.csv").open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    def load_sample_masters(self):
        supplier_result = import_suppliers(SAMPLES / "SAMPLE_suppliers_2026-09-27.csv", commit=True)
        product_result = import_products(SAMPLES / "SAMPLE_products_2026-09-27.csv", commit=True)
        return supplier_result, product_result

    def test_identical_reimports_write_nothing_and_never_touch_ledger(self):
        events_before, lines_before = LedgerEvent.objects.count(), JournalLine.objects.count()
        first_supplier, first_product = self.load_sample_masters()
        second_supplier, second_product = self.load_sample_masters()
        self.assertEqual((first_supplier.inserted_rows, first_product.inserted_rows), (1, 10))
        self.assertEqual((second_supplier.inserted_rows, second_product.inserted_rows), (0, 0))
        self.assertEqual((SupplierChange.objects.count(), ProductComplianceChange.objects.count()), (0, 0))
        self.assertEqual((LedgerEvent.objects.count(), JournalLine.objects.count()),
                         (events_before, lines_before))

    def test_supplier_pii_legal_name_change_and_missing_snapshot_are_refused(self):
        rows = self.rows("suppliers")
        pii = [{**rows[0], "payment_terms": "send to finance" + "@" + "example.test"}]
        with self.assertRaisesRegex(ImportRefused, "PII detected in payment_terms"):
            import_suppliers(self.source("suppliers", "SAMPLE_suppliers_2026-09-28.csv", pii))
        import_suppliers(SAMPLES / "SAMPLE_suppliers_2026-09-27.csv", commit=True)
        renamed = [{**rows[0], "legal_name": "Changed Supplier"}]
        with self.assertRaisesRegex(ImportRefused, "supplier field legal_name cannot change"):
            import_suppliers(self.source("suppliers", "SAMPLE_suppliers_2026-09-28.csv", renamed), commit=True)
        Supplier.objects.create(
            supplier_ref="SUP-002", legal_name="Second Synthetic Supplier", country="TW",
            currency="TWD", default_incoterm="EXW", payment_terms="Prepaid",
            can_invoice_to_tax_id="unknown", declaration_ref="", evidence_ref="synthetic",
            source_filename="SAMPLE_suppliers_2026-09-27.csv", dataset_kind="SAMPLE",
        )
        with self.assertRaisesRegex(ImportRefused, "a missing supplier is not a deletion: SUP-002"):
            import_suppliers(self.source("suppliers", "SAMPLE_suppliers_2026-09-28.csv", rows), commit=True)

    def test_product_declaration_guard_and_filename_classification(self):
        import_suppliers(SAMPLES / "SAMPLE_suppliers_2026-09-27.csv", commit=True)
        rows = self.rows("products")
        cleared = [{**rows[0], "ingredient_ref": "compliance/suppliers/ink.pdf"}, *rows[1:]]
        with self.assertRaisesRegex(
                ImportRefused, "a product cannot be cleared by a supplier with no declaration on file"):
            import_products(self.source("products", "SAMPLE_products_2026-09-28.csv", cleared))
        for kind, importer, rows_for_kind in (
                ("suppliers", import_suppliers, self.rows("suppliers")),
                ("products", import_products, rows)):
            with self.subTest(kind=kind), self.assertRaisesRegex(ImportRefused, "Unclassified"):
                importer(self.source(kind, f"SAMPLE_{kind}.csv", rows_for_kind))

    def test_po_guard_names_all_then_only_the_remaining_nine(self):
        self.load_sample_masters()
        accounting_before = (LedgerEvent.objects.count(), JournalLine.objects.count())
        all_skus = list(Product.objects.order_by("sku").values_list("sku", flat=True))
        with self.assertRaises(PoBlocked) as blocked:
            assert_po_eligible(all_skus)
        self.assertTrue(all(sku in str(blocked.exception) for sku in all_skus))

        supplier_rows = self.rows("suppliers")
        supplier_rows[0]["declaration_ref"] = "compliance/suppliers/SUP-001-declaration.pdf"
        supplier_rows[0]["evidence_ref"] = "declaration update"
        import_suppliers(self.source(
            "suppliers", "SAMPLE_suppliers_2026-09-28.csv", supplier_rows), commit=True)
        product_rows = self.rows("products")
        cleared_sku = product_rows[0]["sku"]
        product_rows[0]["ingredient_ref"] = "compliance/suppliers/SUP-001-ingredients.pdf"
        product_rows[0]["evidence_ref"] = "ingredient update"
        import_products(self.source(
            "products", "SAMPLE_products_2026-09-28.csv", product_rows), commit=True)
        assert_po_eligible([cleared_sku])
        with self.assertRaises(PoBlocked) as remaining:
            assert_po_eligible(all_skus)
        self.assertNotIn(cleared_sku, str(remaining.exception))
        self.assertTrue(all(sku in str(remaining.exception) for sku in all_skus if sku != cleared_sku))
        self.assertEqual((SupplierChange.objects.count(), ProductComplianceChange.objects.count()), (1, 1))
        self.assertEqual((LedgerEvent.objects.count(), JournalLine.objects.count()), accounting_before)

    def test_new_models_are_registered_read_only(self):
        for model in (Supplier, SupplierChange, ProductComplianceChange):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(None))
            self.assertFalse(model_admin.has_change_permission(None))
            self.assertFalse(model_admin.has_delete_permission(None))

    def test_unknown_supplier_duplicate_sku_and_invalid_conversion_are_refused(self):
        import_suppliers(SAMPLES / "SAMPLE_suppliers_2026-09-27.csv", commit=True)
        rows = self.rows("products")
        cases = (
            ([{**rows[0], "supplier_ref": "SUP-999"}], "unknown supplier_ref: SUP-999"),
            ([rows[0], rows[0]], "duplicate sku in product file"),
            ([{**rows[0], "pieces_per_sale_unit": "1.5"}],
             "pieces_per_sale_unit must be a positive whole number"),
        )
        for changed_rows, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ImportRefused, message):
                import_products(self.source(
                    "products", "SAMPLE_products_2026-09-28.csv", changed_rows))

    def test_reference_fixture_must_be_explicitly_authored(self):
        fixture = {**load_schema("suppliers"), "source": "observed"}
        with patch("ops.file_intake.load_schema", return_value=fixture), self.assertRaisesRegex(
                ImportRefused, "suppliers schema fixture must have source authored"):
            manifest("suppliers")

    def test_zero_conversion_is_refused_by_intake_and_database(self):
        import_suppliers(SAMPLES / "SAMPLE_suppliers_2026-09-27.csv", commit=True)
        rows = self.rows("products")
        with self.assertRaisesRegex(ImportRefused, "pieces_per_sale_unit must be a positive whole number"):
            import_products(self.source("products", "SAMPLE_products_2026-09-28.csv", [
                {**rows[0], "pieces_per_sale_unit": "0"}
            ]))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.create(sku="TS-ZZ-999-S", name="Invalid conversion", uom="PC",
                                   pieces_per_sale_unit=0)


class ComplianceFailClosedTests(TransactionTestCase):
    migrate_from = ("ops", "0007_supplier_product_compliance")
    migrate_to = ("ops", "0008_product_supplier_compliance_ref_shape")
    sku = "TS-FL-001-S"
    valid_ingredient = "compliance/suppliers/ingredients.pdf"
    valid_declaration = "compliance/suppliers/declaration.pdf"
    invalid_ingredients = ("", "unknown", "TBD", "pending", "compliance/suppliers/")

    def _restore_latest_schema(self):
        Product.objects.filter(pk=self.sku).update(ingredient_ref=self.valid_ingredient)
        Supplier.objects.filter(supplier_ref="SUP-001").update(
            declaration_ref=self.valid_declaration)
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_guard_and_database_constraints_fail_closed(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        OldSupplier = old_apps.get_model("ops", "Supplier")
        OldProduct = old_apps.get_model("ops", "Product")
        supplier = OldSupplier.objects.create(
            supplier_ref="SUP-001", legal_name="Synthetic Supplier", country="TW",
            currency="TWD", default_incoterm="EXW", payment_terms="Prepaid",
            can_invoice_to_tax_id="unknown", declaration_ref=self.valid_declaration,
            evidence_ref="synthetic", source_filename="SAMPLE_suppliers.csv",
            dataset_kind="SAMPLE",
        )
        OldProduct.objects.create(
            sku=self.sku, name="Synthetic Product", uom="PK", pack_qty=1,
            supplier=supplier, ingredient_ref=self.valid_ingredient,
        )
        self.addCleanup(self._restore_latest_schema)

        for invalid in self.invalid_ingredients:
            with self.subTest(guard_value=invalid):
                OldProduct.objects.filter(pk=self.sku).update(ingredient_ref=invalid)
                with self.assertRaisesRegex(PoBlocked, self.sku):
                    assert_po_eligible([self.sku])
                OldProduct.objects.filter(pk=self.sku).update(
                    ingredient_ref=self.valid_ingredient)

        OldSupplier.objects.filter(pk=supplier.pk).update(
            declaration_ref="compliance/suppliers/")
        with self.assertRaisesRegex(PoBlocked, self.sku):
            assert_po_eligible([self.sku])
        OldSupplier.objects.filter(pk=supplier.pk).update(
            declaration_ref=self.valid_declaration)

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])

        for invalid in self.invalid_ingredients:
            with self.subTest(check_value=invalid), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Product.objects.filter(pk=self.sku).update(ingredient_ref=invalid)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Supplier.objects.filter(pk=supplier.pk).update(
                    declaration_ref="compliance/suppliers/")
