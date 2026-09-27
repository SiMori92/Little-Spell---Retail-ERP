import hashlib
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, transaction
from django.test import TestCase, TransactionTestCase

from core.models import SecretRotation


class RecordSecretRotationTests(TestCase):
    def test_records_digest_and_metadata_but_never_secret(self):
        out = StringIO()
        call_command("record_secret_rotation", "--actor", "founder", "--evidence-ref", "vault-42",
                     "--db-password-rotated", stdout=out)
        row = SecretRotation.objects.get()
        self.assertEqual(row.secret_key_sha256, hashlib.sha256(settings.SECRET_KEY.encode()).hexdigest())
        self.assertTrue(row.db_password_rotated)
        self.assertNotIn(settings.SECRET_KEY, out.getvalue())
        self.assertNotIn(settings.SECRET_KEY, repr(row.__dict__))

    def test_same_running_key_is_noop(self):
        for _ in range(2):
            call_command("record_secret_rotation", "--actor", "founder", "--evidence-ref", "vault-42",
                         stdout=StringIO())
        self.assertEqual(SecretRotation.objects.count(), 1)

    def test_actor_and_evidence_cannot_be_blank(self):
        for actor, evidence in ((" ", "x"), ("x", " ")):
            with self.assertRaises(CommandError):
                call_command("record_secret_rotation", "--actor", actor, "--evidence-ref", evidence,
                             stdout=StringIO())


class SecretRotationAppendOnlyTests(TransactionTestCase):
    def setUp(self):
        self.row = SecretRotation.objects.create(actor="a", evidence_ref="e",
            secret_key_sha256="0" * 64)

    def test_update_and_delete_are_refused_by_database(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            SecretRotation.objects.filter(pk=self.row.pk).update(actor="changed")
        with self.assertRaises(DatabaseError), transaction.atomic():
            SecretRotation.objects.filter(pk=self.row.pk).delete()
