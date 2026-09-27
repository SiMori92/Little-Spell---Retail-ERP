"""Slice U contract tests: pieces for stock, sale units for customer quantities."""

import csv
from pathlib import Path
from tempfile import TemporaryDirectory

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase, TransactionTestCase

from acct.models import JournalLine, MANUAL_EVENT_TYPES, WacPosition
from core.models import DatasetSettings
from ops.file_intake import import_counts, import_ig_deals, import_products
from ops.intake import ImportRefused
from ops.models import OPS_EVENT_TYPES, IgDeal, InventoryMove, OnHand, OrderLine, Product, StockCountLine


class UnitVocabularyTests(TestCase):
    def setUp(self):
        DatasetSettings.objects.get_or_create(pk=1, defaults={"dataset_kind": "SAMPLE"})
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def old_header(self, kind, field):
        headers = {
            "products": ["sku", "name", "pack_qty", "supplier_ref", "ingredient_ref", "evidence_ref"],
            "counts": ["counted_at", "evidence_ref", "sku", "qty_packs",
                       "agreed_unit_cost_twd", "condition"],
            "ig_deals": ["deal_id", "line_no", "customer_ref", "status", "enquiry_at",
                         "quoted_at", "quote_twd", "follow_up_on", "lost_reason", "sku",
                         "qty_packs", "unit_price_twd", "shipping_charged_twd", "ship_country",
                         "paid_at", "wallet_txn_id", "ship_date", "consent_marketing",
                         "journey_sent", "evidence_ref"],
        }
        filenames = {"products": "SAMPLE_products_2026-09-28.csv",
                     "counts": "SAMPLE_count_2026-09-28.csv",
                     "ig_deals": "SAMPLE_ig_deals_2026-10.csv"}
        path = Path(self.temp.name) / filenames[kind]
        with path.open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow(headers[kind])
        return path

    def test_v1_unit_headers_are_refused_by_old_and_required_field_names(self):
        cases = (
            ("products", import_products, "pack_qty", "pieces_per_sale_unit"),
            ("counts", import_counts, "qty_packs", "qty_pieces"),
            ("ig_deals", import_ig_deals, "qty_packs", "qty_sale_units"),
        )
        for kind, importer, old, new in cases:
            with self.subTest(kind=kind), self.assertRaisesRegex(
                    ImportRefused, rf"{kind} file uses header v1 \({old}\); v2 requires {new}"):
                importer(self.old_header(kind, old))

    def test_models_expose_only_piece_or_sale_unit_quantity_names(self):
        expected = {
            Product: {"pieces_per_sale_unit"},
            OrderLine: {"qty_sale_units"},
            IgDeal: {"qty_sale_units"},
            InventoryMove: {"qty_delta_pieces"},
            StockCountLine: {"qty_pieces"},
            OnHand: {"qty_pieces"},
            WacPosition: {"qty_pieces"},
            JournalLine: {"qty_delta_pieces"},
        }
        forbidden = {"pack_qty", "qty_packs", "qty_delta_packs"}
        for model, required in expected.items():
            names = {field.name for field in model._meta.get_fields()}
            with self.subTest(model=model.__name__):
                self.assertTrue(required <= names)
                self.assertFalse(forbidden & names)

    def test_piece_uom_conversion_and_whole_wac_are_database_checks(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.create(sku="BAD-UOM", name="Bad UOM", uom="PK",
                                   pieces_per_sale_unit=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            WacPosition.objects.create(sku="FRACTIONAL", qty_pieces="1.5000", value_twd=1)

    def test_catalogue_remains_exactly_twenty_eight_types(self):
        self.assertEqual((len(OPS_EVENT_TYPES), len(MANUAL_EVENT_TYPES)), (22, 6))
        self.assertEqual(len(set(OPS_EVENT_TYPES) | set(MANUAL_EVENT_TYPES)), 28)


class UnitMigrationRefusalTests(TransactionTestCase):
    reset_sequences = True
    migrate_from = [("ops", "0010_igdeal_date_order"),
                    ("acct", "0006_remove_journalline_acct_line_one_side_and_more")]
    migrate_to = [("ops", "0011_piece_inventory_unit")]

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        self.old_apps = executor.loader.project_state(self.migrate_from).apps
        self.OldSettings = self.old_apps.get_model("core", "DatasetSettings")
        self.OldProduct = self.old_apps.get_model("ops", "Product")
        self.OldMove = self.old_apps.get_model("ops", "InventoryMove")
        self.settings, _ = self.OldSettings.objects.get_or_create(
            pk=1, defaults={"dataset_kind": "SAMPLE"}
        )
        self.settings.dataset_kind = "SAMPLE"
        self.settings.save(update_fields=["dataset_kind"])

    def tearDown(self):
        if not MigrationRecorder(connection).migration_qs.filter(
                app="ops", name="0011_piece_inventory_unit").exists():
            self.OldMove.objects.all().delete()
            self.OldProduct.objects.all().delete()
            self.OldSettings.objects.filter(pk=1).update(dataset_kind="SAMPLE")
        MigrationExecutor(connection).migrate(
            MigrationExecutor(connection).loader.graph.leaf_nodes()
        )
        super().tearDown()

    def test_factor_one_product_and_inventory_move_migrate_forward_in_place(self):
        safe = self.OldProduct.objects.create(
            sku="TS-FL-001-S", name="Safe factor one", uom="PK", pack_qty=1
        )
        self.OldMove.objects.create(
            product=safe, kind="opening", qty_delta_packs=7, value_delta_twd=35,
            occurred_at="2026-09-27T00:00:00Z", idempotency_key="migration-safe",
            source_filename="SAMPLE_count.csv", dataset_kind="SAMPLE",
        )
        MigrationExecutor(connection).migrate(self.migrate_to)
        new_apps = MigrationExecutor(connection).loader.project_state(self.migrate_to).apps
        NewProduct = new_apps.get_model("ops", "Product")
        NewMove = new_apps.get_model("ops", "InventoryMove")
        migrated = NewProduct.objects.get(pk=safe.pk)
        self.assertEqual(
            (migrated.uom, migrated.pieces_per_sale_unit,
             NewMove.objects.get(idempotency_key="migration-safe").qty_delta_pieces),
            ("PC", 1, 7),
        )

    def test_factor_twelve_inventory_move_refuses_with_verbatim_i7_message(self):
        product = self.OldProduct.objects.create(
            sku="TS-MN-006-P", name="Migration refusal", uom="PK", pack_qty=12
        )
        self.OldMove.objects.create(
            product=product, kind="opening", qty_delta_packs=1, value_delta_twd=10,
            occurred_at="2026-09-27T00:00:00Z", idempotency_key="migration-refusal",
            source_filename="SAMPLE_count.csv", dataset_kind="SAMPLE",
        )
        with self.assertRaisesRegex(
                RuntimeError,
                r"^Unit migration refused: SAMPLE data holds pack quantities for TS-MN-006-P\. "
                r"Reset the SAMPLE database and re-import the samples \(catalogue Addendum F\.4\)\.$"):
            MigrationExecutor(connection).migrate(self.migrate_to)

    def test_actual_dataset_refuses_unconditionally(self):
        self.settings.dataset_kind = "ACTUAL"
        self.settings.save(update_fields=["dataset_kind"])
        with self.assertRaisesRegex(RuntimeError, "Unit migration refused: ACTUAL dataset rows exist"):
            MigrationExecutor(connection).migrate(self.migrate_to)
