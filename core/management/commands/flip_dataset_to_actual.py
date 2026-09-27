"""Switch an empty, newly provisioned database from SAMPLE to ACTUAL.

A database that has ever held SAMPLE business rows is never converted in place.
Production is a separate environment with a new empty database, a newly rotated
secret, and an explicit real opening-funding entry. This prevents synthetic and
real facts from ever coexisting and removes the withdrawn sample-seed reversal.
"""

import hashlib
from datetime import datetime, time
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from acct.models import Account, AcctManualEntry
from acct.posting import PostingError, plan, post_event
from core.models import DatasetKind, DatasetSettings, SecretRotation

MONEY_EXPONENT = Decimal("0.0001")
FUNDING_TYPES = {"capital": "3111", "loan": "2281"}


def _required_text(value, option):
    value = (value or "").strip()
    if not value:
        raise CommandError(f"--{option} is required and cannot be blank")
    return value


def sample_business_tables():
    """Return every concrete dataset-bearing table that contains SAMPLE rows."""
    tables = []
    for model in apps.get_models():
        if model is DatasetSettings or model._meta.proxy or not model._meta.managed:
            continue
        try:
            model._meta.get_field("dataset_kind")
        except Exception:
            continue
        if model.objects.filter(dataset_kind=DatasetKind.SAMPLE).exists():
            tables.append(model._meta.db_table)
    return sorted(tables)


class Command(BaseCommand):
    help = "Post real opening funding and switch a new empty database permanently to ACTUAL."

    def add_arguments(self, parser):
        parser.add_argument("--amount", required=True)
        parser.add_argument("--funding-type", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--evidence-ref", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        amount = self._parse_amount(options["amount"])
        funding_type = options["funding_type"]
        if funding_type not in FUNDING_TYPES:
            raise CommandError("--funding-type must be one of: capital, loan")
        actor = _required_text(options["actor"], "actor")
        evidence_ref = _required_text(options["evidence_ref"], "evidence-ref")
        dry_run = options["dry_run"]

        settings_row = DatasetSettings.load()
        sample_tables = sample_business_tables()
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).hexdigest()
        latest = SecretRotation.objects.order_by("-rotated_at", "-id").first()
        checks = [
            ("dataset is not already ACTUAL", settings_row.dataset_kind != DatasetKind.ACTUAL,
             "dataset_kind is already ACTUAL"),
            ("database contains no SAMPLE business rows", not sample_tables,
             "SAMPLE rows exist in table(s): " + ", ".join(sample_tables)),
            ("a secret rotation is recorded", latest is not None, "no SecretRotation row exists"),
            ("latest rotation matches the running SECRET_KEY",
             latest is not None and latest.secret_key_sha256 == digest,
             "latest SecretRotation does not match the running SECRET_KEY"),
            ("opening amount is positive and exact to 4 dp", True, ""),
            ("funding type is capital or loan", True, ""),
            ("actor is present", True, ""),
            ("evidence reference is present", True, ""),
        ]
        for label, passed, reason in checks:
            self.stdout.write(f"{'PASS' if passed else 'FAIL'}: {label}" + (f" — {reason}" if reason else ""))
        credit = FUNDING_TYPES[funding_type]
        self.stdout.write(f"Dr 1121 {amount:.4f} TWD")
        self.stdout.write(f"Cr {credit} {amount:.4f} TWD")
        if dry_run:
            self.stdout.write("--dry-run: nothing written.")

        failures = [reason for _, passed, reason in checks if not passed]
        if failures:
            raise CommandError("REFUSED: " + "; ".join(failures))
        if dry_run:
            return

        with transaction.atomic():
            locked = DatasetSettings.objects.select_for_update().get(pk=settings_row.pk)
            if locked.dataset_kind == DatasetKind.ACTUAL:
                raise CommandError("REFUSED: dataset_kind is already ACTUAL")
            remaining = sample_business_tables()
            if remaining:
                raise CommandError("REFUSED: SAMPLE rows exist in table(s): " + ", ".join(remaining))
            current_rotation = SecretRotation.objects.order_by("-rotated_at", "-id").first()
            if current_rotation is None or current_rotation.secret_key_sha256 != digest:
                raise CommandError("REFUSED: latest SecretRotation does not match the running SECRET_KEY")

            occurred_at = timezone.make_aware(datetime.combine(timezone.localdate(), time(12)))
            entry = AcctManualEntry(
                event_type="owner.funds_moved", occurred_at=occurred_at,
                period=occurred_at.strftime("%Y-%m"), amount=amount, currency="TWD",
                payload={"funds_type": funding_type}, basis="actual", evidence_ref=evidence_ref,
                created_by=actor, idempotency_key=f"actual-opening:{evidence_ref}",
            )
            try:
                planned = plan(entry)
            except PostingError as exc:
                raise CommandError(str(exc)) from exc
            expected = [("1121", amount, Decimal(0)), (credit, Decimal(0), amount)]
            observed = [(leg.account, leg.debit, leg.credit) for leg in planned]
            if observed != expected:
                raise CommandError("REFUSED: opening rule did not produce exactly the authorised two lines")
            missing = sorted({code for code, _, _ in expected} - set(
                Account.objects.filter(code__in=["1121", credit]).values_list("code", flat=True)
            ))
            if missing:
                raise CommandError("REFUSED: missing account(s): " + ", ".join(missing))
            entry.save(force_insert=True)
            post_event(entry, dataset_kind_override=DatasetKind.ACTUAL)
            locked.dataset_kind = DatasetKind.ACTUAL
            locked.flipped_to_actual_at = timezone.now()
            locked.seed_journal_entry_ref = ""
            locked.save(update_fields=["dataset_kind", "flipped_to_actual_at", "seed_journal_entry_ref", "updated_at"])
        self.stdout.write("dataset_kind is now ACTUAL; the opening entry posted with exactly two lines.")

    @staticmethod
    def _parse_amount(raw):
        try:
            amount = Decimal(str(raw))
        except (InvalidOperation, ValueError) as exc:
            raise CommandError(f"--amount {raw!r} is not an exact decimal") from exc
        if not amount.is_finite() or amount <= 0:
            raise CommandError("--amount must be greater than zero and finite")
        try:
            exact = amount == amount.quantize(MONEY_EXPONENT)
        except InvalidOperation:
            exact = False
        if not exact:
            raise CommandError("--amount carries more than 4 decimal places (numeric(18,4))")
        return amount.quantize(MONEY_EXPONENT)
