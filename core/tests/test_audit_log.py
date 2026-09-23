from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from core.middleware import clear_actor, set_actor
from core.models import AuditAction, AuditLogEntry

# Every field on the audit model. If a future change adds a column able to hold a
# value rather than a field name, this list forces the change to be deliberate.
EXPECTED_FIELDS = {
    "id", "at", "actor_id", "actor_username", "action",
    "app_label", "model_name", "object_pk", "changed_fields",
    "request_method", "request_path",
}


class AuditLogRecordsChangesTests(TestCase):
    def setUp(self):
        clear_actor()

    def test_creating_a_row_writes_a_create_entry(self):
        user = get_user_model().objects.create_user(username="agent1", password="x")
        entry = AuditLogEntry.objects.filter(
            app_label="auth", model_name="user", object_pk=str(user.pk)
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.action, AuditAction.CREATE)

    def test_updating_a_row_records_only_the_changed_field_names(self):
        user = get_user_model().objects.create_user(username="agent1", password="x")
        user.is_staff = True
        user.save()
        entry = AuditLogEntry.objects.filter(action=AuditAction.UPDATE).latest("id")
        self.assertEqual(entry.changed_fields, ["is_staff"])

    def test_the_acting_user_is_recorded(self):
        actor = get_user_model().objects.create_user(username="founder", password="x")
        set_actor(actor.pk, "founder", "POST", "/admin/auth/user/add/")
        try:
            get_user_model().objects.create_user(username="someone", password="x")
        finally:
            clear_actor()
        entry = AuditLogEntry.objects.latest("id")
        self.assertEqual(entry.actor_username, "founder")
        self.assertEqual(entry.actor_id, actor.pk)
        self.assertEqual(entry.request_method, "POST")

    def test_deleting_a_row_writes_a_delete_entry(self):
        user = get_user_model().objects.create_user(username="gone", password="x")
        pk = str(user.pk)
        user.delete()
        self.assertTrue(
            AuditLogEntry.objects.filter(action=AuditAction.DELETE, object_pk=pk).exists()
        )

    def test_the_audit_log_does_not_audit_itself(self):
        before = AuditLogEntry.objects.count()
        get_user_model().objects.create_user(username="one", password="x")
        # Exactly one new row: the user's CREATE. Not that row plus a row about it.
        self.assertEqual(AuditLogEntry.objects.count(), before + 1)


class AuditLogCarriesNoPIITests(TestCase):
    def test_the_table_has_no_column_that_can_hold_a_field_value(self):
        """The no-PII guarantee is structural, not a promise.

        `changed_fields` holds field NAMES. There is no column for a buyer name or a
        street address to land in, so a Slice A model carrying one cannot leak it here.
        """
        self.assertEqual({f.name for f in AuditLogEntry._meta.get_fields()}, EXPECTED_FIELDS)

    def test_changed_fields_contains_names_not_values(self):
        user = get_user_model().objects.create_user(
            username="private_person", password="x", email="private@" + "example.com"
        )
        user.email = "changed@" + "example.com"
        user.save()
        entry = AuditLogEntry.objects.filter(action=AuditAction.UPDATE).latest("id")
        self.assertIn("email", entry.changed_fields)
        serialised = str(entry.changed_fields)
        self.assertNotIn("private@" + "example.com", serialised)
        self.assertNotIn("changed@" + "example.com", serialised)


class AuditLogIsAppendOnlyTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user(username="subject", password="x")
        self.entry = AuditLogEntry.objects.latest("id")

    def test_model_save_refuses_to_modify_an_existing_entry(self):
        self.entry.actor_username = "someone_else"
        with self.assertRaises(RuntimeError):
            self.entry.save()

    def test_model_delete_refuses(self):
        with self.assertRaises(RuntimeError):
            self.entry.delete()

    def test_the_database_refuses_an_update_even_from_raw_sql(self):
        """The application check can be bypassed. The trigger cannot."""
        with self.assertRaises(Exception), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE core_auditlogentry SET actor_username = 'forged' WHERE id = %s",
                    [self.entry.pk],
                )

    def test_the_database_refuses_a_delete_even_from_raw_sql(self):
        with self.assertRaises(Exception), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM core_auditlogentry WHERE id = %s", [self.entry.pk]
                )
