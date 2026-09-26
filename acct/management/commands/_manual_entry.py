"""Shared input boundary for the six accounting-originated entry commands."""

import hashlib
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from acct.models import Account, AcctManualEntry, Period
from acct.posting import PostingError, plan


PERIOD_PATTERN = re.compile(r"\d{4}-(0[1-9]|1[0-2])\Z")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
CENT = Decimal("0.0001")


def required_text(value, option, max_length=None):
    if not value or not value.strip():
        raise CommandError(f"--{option} is required and cannot be blank")
    value = value.strip()
    if max_length and len(value) > max_length:
        raise CommandError(f"--{option} exceeds {max_length} characters")
    return value


def positive_amount(raw):
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        raise CommandError("--amount must be a positive TWD decimal") from exc
    if not value.is_finite() or value <= 0 or value >= Decimal("100000000000000"):
        raise CommandError("--amount must be positive TWD with at most four decimal places and fit decimal(18,4)")
    try:
        exact = value == value.quantize(CENT)
    except InvalidOperation:
        exact = False
    if not exact:
        raise CommandError("--amount must be positive TWD with at most four decimal places and fit decimal(18,4)")
    return value


def natural_key(event_type, period, evidence_ref):
    digest = hashlib.sha256(evidence_ref.encode("utf-8")).hexdigest()
    return f"manual:{event_type}:{period}:{digest}"


class ManualEntryCommand(BaseCommand):
    """Validate, preview with the frozen posting rule, then create an unposted row."""

    event_type = None

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--evidence-ref", required=True)
        parser.add_argument("--period", required=True)
        parser.add_argument("--occurred-on", required=True)
        parser.add_argument("--dry-run", action="store_true")
        self.add_entry_arguments(parser)

    def add_entry_arguments(self, parser):
        raise NotImplementedError

    def entry_fields(self, options):
        raise NotImplementedError

    @transaction.atomic
    def handle(self, *args, **options):
        actor = required_text(options["actor"], "actor", 80)
        evidence_ref = required_text(options["evidence_ref"], "evidence-ref", 255)
        period = options["period"]
        if not PERIOD_PATTERN.fullmatch(period):
            raise CommandError("--period must be YYYY-MM")
        if not DATE_PATTERN.fullmatch(options["occurred_on"]):
            raise CommandError("--occurred-on must be an ISO date YYYY-MM-DD")
        try:
            occurred_on = date.fromisoformat(options["occurred_on"])
        except ValueError as exc:
            raise CommandError("--occurred-on must be an ISO date YYYY-MM-DD") from exc
        if occurred_on.strftime("%Y-%m") != period:
            raise CommandError(f"--occurred-on must fall inside period {period}")

        # Command-specific input (including an empty basis note) fails before any DB read.
        fields = self.entry_fields(options)

        # Lock an existing period so close and create cannot cross in this transaction.
        period_row = Period.objects.select_for_update().filter(pk=period).first()
        if period_row and period_row.status == "CLOSED":
            raise CommandError(f"accounting period {period} is CLOSED")

        occurred_at = timezone.make_aware(datetime.combine(occurred_on, time(12)))
        candidate = AcctManualEntry(
            event_type=self.event_type,
            occurred_at=occurred_at,
            period=period,
            currency="TWD",
            evidence_ref=evidence_ref,
            created_by=actor,
            idempotency_key=natural_key(self.event_type, period, evidence_ref),
            **fields,
        )
        existing = AcctManualEntry.objects.filter(idempotency_key=candidate.idempotency_key).first()
        if existing:
            compared = ("event_type", "occurred_at", "period", "amount", "currency", "payload", "basis",
                        "evidence_ref", "needs_prof_conf", "reverses_id", "created_by")
            if any(getattr(existing, field) != getattr(candidate, field) for field in compared):
                raise CommandError("natural key already exists with different entry details; use a distinct evidence reference")
            self.stdout.write(f"existing unposted manual entry {existing.pk}" if not existing.posted_entry_id
                              else f"existing posted manual entry {existing.pk}")
            if options["dry_run"]:
                self._print_lines(existing)
            return

        try:
            lines = plan(candidate)
        except PostingError as exc:
            raise CommandError(str(exc)) from exc
        # The frozen rule names codes; check availability before saving an unpostable row.
        codes = {line.account for line in lines}
        found = {account.code: account for account in Account.objects.filter(code__in=codes)}
        for code in sorted(codes):
            if code not in found:
                raise CommandError(f"account {code} does not exist")
            if found[code].is_reserved:
                raise CommandError(f"account {code} is RESERVED")
        if options["dry_run"]:
            self._write_lines(lines)
            return
        try:
            with transaction.atomic():
                candidate.save(force_insert=True)
        except IntegrityError as exc:
            # The unique key/DB guards remain authoritative under concurrent calls.
            raise CommandError("manual entry could not be created; check the natural key and period") from exc
        self.stdout.write(f"created unposted manual entry {candidate.pk}; post with: post_accounting_event manual {candidate.pk}")

    def _print_lines(self, entry):
        try:
            self._write_lines(plan(entry))
        except PostingError as exc:
            raise CommandError(str(exc)) from exc

    def _write_lines(self, lines):
        for line in lines:
            if line.debit:
                self.stdout.write(f"Dr {line.account} {line.debit:.4f} TWD")
            if line.credit:
                self.stdout.write(f"Cr {line.account} {line.credit:.4f} TWD")
