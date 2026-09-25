"""Forward/backward migration test.

BUILD_TASK §4.3: "every migration reviewed for reversibility". A migration that
cannot be unwound is a migration you cannot back out of a bad deploy, and a Railway
deploy runs migrations against the database holding the books.
"""

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


def table_exists(name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [f"public.{name}"])
        return cursor.fetchone()[0]


def role_exists(name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", [name])
        return cursor.fetchone()[0]


class MigrationsRunForwardAndBackwardTests(TransactionTestCase):
    """Roll `core` all the way to zero and all the way back."""

    # NOT serialized_rollback. Django restores serialized rows by calling save() on
    # objects that already have a pk, which issues an UPDATE — and the append-only
    # trigger on core_auditlogentry rejects it, correctly. The rollback helper is
    # unnecessary here anyway: every test in this class re-migrates, and
    # DatasetSettings.load() recreates the singleton as SAMPLE on demand.

    def tearDown(self):
        # Slice A's ops controls depend on core roles. Restore the full graph.
        call_command("migrate", verbosity=0)

    def test_core_migrates_backward_to_zero_and_forward_again(self):
        self.assertTrue(table_exists("core_auditlogentry"))
        self.assertTrue(table_exists("core_datasetsettings"))

        call_command("migrate", "core", "zero", verbosity=0)
        self.assertFalse(table_exists("core_auditlogentry"))
        self.assertFalse(table_exists("core_datasetsettings"))

        call_command("migrate", "core", verbosity=0)
        self.assertTrue(table_exists("core_auditlogentry"))
        self.assertTrue(table_exists("core_datasetsettings"))

    def test_the_singleton_is_restored_by_migrating_forward(self):
        call_command("migrate", "core", "zero", verbosity=0)
        call_command("migrate", "core", verbosity=0)
        from core.models import DatasetKind, DatasetSettings

        row = DatasetSettings.objects.get(pk=1)
        self.assertEqual(row.dataset_kind, DatasetKind.SAMPLE)

    def test_the_append_only_trigger_is_recreated_by_migrating_forward(self):
        call_command("migrate", "core", "zero", verbosity=0)
        call_command("migrate", "core", verbosity=0)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger "
                "WHERE tgname = 'core_auditlogentry_append_only')"
            )
            self.assertTrue(cursor.fetchone()[0])


class DatabaseRolesTests(TransactionTestCase):
    """Catalogue-only assertions; see the note above on serialized_rollback."""

    def test_the_three_roles_exist(self):
        for role in ("ops_writer", "acct_writer", "reporter"):
            with self.subTest(role=role):
                self.assertTrue(role_exists(role), f"role {role} was not created by migration")

    def test_default_privileges_are_recorded_for_future_tables(self):
        """ALTER DEFAULT PRIVILEGES applied, so tables Slice A adds inherit the grants."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_default_acl d "
                "JOIN pg_namespace n ON n.oid = d.defaclnamespace "
                "WHERE n.nspname = 'public'"
            )
            self.assertGreater(cursor.fetchone()[0], 0)

    def test_reporter_holds_select_and_no_write_grant_anywhere(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE grantee = 'reporter' AND privilege_type IN "
                "('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')"
            )
            self.assertEqual(cursor.fetchone()[0], 0, "reporter must be SELECT only")

    def test_slice_b_accounting_tables_exist(self):
        """Slice B creates its accounting tables, including SKU valuation."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename LIKE 'acct\\_%'"
            )
            self.assertEqual(cursor.fetchone()[0], 10)

    def test_reapplying_grants_does_not_restore_journal_update(self):
        call_command("apply_table_grants", verbosity=0)
        with connection.cursor() as cursor:
            for table in ("acct_journalentry", "acct_journalline"):
                cursor.execute("SELECT has_table_privilege('acct_writer', %s, 'UPDATE')", [table])
                self.assertFalse(cursor.fetchone()[0])


class NoMissingMigrationsTests(TransactionTestCase):
    def test_models_and_migrations_are_in_sync(self):
        """A model change without `makemigrations` breaks the deploy, not the test run."""
        executor = MigrationExecutor(connection)
        changes = executor.loader.detect_conflicts()
        self.assertEqual(changes, {})
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)


class SliceZeroBoundaryTests(TransactionTestCase):
    """Ops facts and Slice B accounting models stay in separate apps."""

    def test_ops_and_accounting_models_are_separate(self):
        from django.apps import apps

        ops_names = {m.__name__ for m in apps.get_app_config("ops").get_models()}
        self.assertTrue({"Product", "Channel", "Order", "OrderLine", "Shipment",
                         "InventoryMove", "LedgerEvent"} <= ops_names)
        self.assertEqual(
            {m.__name__ for m in apps.get_app_config("acct").get_models()},
            {"Account", "FxRate", "Period", "JournalEntry", "JournalLine", "AcctManualEntry", "WacPosition",
             "ClearingCause", "CloseRun", "CloseAudit"},
        )
