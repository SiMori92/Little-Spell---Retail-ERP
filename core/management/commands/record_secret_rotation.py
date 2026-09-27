"""Record deployment-secret rotation evidence without persisting the secret."""

import hashlib

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import SecretRotation


def required_text(value, option):
    value = (value or "").strip()
    if not value:
        raise CommandError(f"--{option} is required and cannot be blank")
    return value


class Command(BaseCommand):
    help = "Record the SHA-256 fingerprint of the running SECRET_KEY after rotation."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--evidence-ref", required=True)
        parser.add_argument("--db-password-rotated", action="store_true")

    def handle(self, *args, **options):
        actor = required_text(options["actor"], "actor")
        evidence_ref = required_text(options["evidence_ref"], "evidence-ref")
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).hexdigest()
        latest = SecretRotation.objects.order_by("-rotated_at", "-id").first()
        if latest and latest.secret_key_sha256 == digest:
            self.stdout.write("No-op: the running SECRET_KEY fingerprint is already recorded.")
            return
        row = SecretRotation.objects.create(
            actor=actor,
            evidence_ref=evidence_ref,
            secret_key_sha256=digest,
            db_password_rotated=options["db_password_rotated"],
        )
        self.stdout.write(f"Secret rotation recorded as row {row.pk}.")
