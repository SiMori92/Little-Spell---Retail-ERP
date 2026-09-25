"""Slice B accounting records. Journal amounts are functional TWD."""

from django.db import models
from django.db.models import Q

from core.models import DatasetKind


MANUAL_EVENT_TYPES = (
    "period.revalued", "period.accrued", "period.accrual_reversed",
    "tax.assessed", "tax.paid", "owner.funds_moved",
)


class Account(models.Model):
    code = models.CharField(max_length=4, primary_key=True)
    name_en = models.CharField(max_length=120)
    name_zh = models.CharField(max_length=120)
    type = models.CharField(max_length=20)
    statement = models.CharField(max_length=20)
    normal_balance = models.CharField(max_length=6)
    statutory_code = models.CharField(max_length=40, blank=True)
    tax_treatment = models.CharField(max_length=20, null=True, blank=True)
    tax_regime = models.CharField(max_length=20, blank=True)
    subledger = models.CharField(max_length=20, blank=True)
    is_reserved = models.BooleanField(default=False)
    is_contra = models.BooleanField(default=False)
    is_closing_only = models.BooleanField(default=False)
    active_from = models.DateField(null=True, blank=True)
    active_to = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=~Q(type="revenue") | Q(tax_treatment__isnull=False),
            name="acct_revenue_has_tax_treatment",
        )]


class FxRate(models.Model):
    class Kind(models.TextChoices):
        PUBLIC = "public"
        CHANNEL = "channel"

    class Source(models.TextChoices):
        BOT = "bot"
        STATED = "stated"
        DERIVED = "derived"
        MANUAL = "manual"

    rate_date = models.DateField()
    currency = models.CharField(max_length=3)
    kind = models.CharField(max_length=7, choices=Kind.choices)
    rate = models.DecimalField(max_digits=12, decimal_places=6)
    rate_source = models.CharField(max_length=7, choices=Source.choices)
    evidence_ref = models.CharField(max_length=255)
    source_event_key = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(rate__gt=0), name="acct_fx_positive"),
            models.CheckConstraint(condition=(Q(kind="public", rate_source__in=["bot", "manual"]) | Q(kind="channel", rate_source__in=["stated", "derived"])), name="acct_fx_source_kind"),
            models.UniqueConstraint(fields=["rate_date", "currency", "kind", "source_event_key"], name="acct_fx_source_unique"),
        ]


class Period(models.Model):
    period = models.CharField(max_length=7, primary_key=True)
    status = models.CharField(max_length=6, default="OPEN")

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(status__in=["OPEN", "CLOSED"]), name="acct_period_status")]


class WacPosition(models.Model):
    """Running weighted-average value per SKU; lots remain traceability only."""

    sku = models.CharField(max_length=20, primary_key=True)
    qty_packs = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    value_twd = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(qty_packs__gte=0, value_twd__gte=0), name="acct_wac_nonnegative")]


class JournalEntry(models.Model):
    occurred_at = models.DateTimeField()
    period = models.CharField(max_length=7)
    dataset_kind = models.CharField(max_length=6, choices=DatasetKind.choices)
    source_kind = models.CharField(max_length=12)
    memo_only = models.BooleanField(default=False)
    source_ref = models.CharField(max_length=255, unique=True)
    reverses = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT)
    memo = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, related_name="lines", on_delete=models.PROTECT)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    sku = models.CharField(max_length=20, null=True, blank=True, db_index=True)
    qty_delta_packs = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    source_ref = models.CharField(max_length=255, null=True, blank=True)
    debit = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    credit = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    txn_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    txn_currency = models.CharField(max_length=3, null=True, blank=True)
    fx_rate = models.ForeignKey(FxRate, null=True, blank=True, on_delete=models.PROTECT)
    memo = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(debit__gte=0, credit__gte=0) & (Q(debit__gt=0, credit=0) | Q(credit__gt=0, debit=0)), name="acct_line_one_side"),
            models.CheckConstraint(condition=Q(txn_currency__isnull=True) | Q(txn_currency="TWD") | (Q(txn_amount__isnull=False) & Q(fx_rate__isnull=False)), name="acct_line_fx_triple"),
        ]


class AcctManualEntry(models.Model):
    event_type = models.CharField(max_length=40, choices=[(x, x) for x in MANUAL_EVENT_TYPES])
    occurred_at = models.DateTimeField()
    period = models.CharField(max_length=7)
    amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    currency = models.CharField(max_length=3)
    fx_rate = models.ForeignKey(FxRate, null=True, blank=True, on_delete=models.PROTECT)
    payload = models.JSONField(default=dict)
    basis = models.CharField(max_length=8, default="actual")
    evidence_ref = models.CharField(max_length=255, null=True, blank=True)
    needs_prof_conf = models.BooleanField(default=False)
    first_flagged_on = models.DateField(null=True, blank=True)
    reverses = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=255, unique=True)
    posted_entry = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.PROTECT)
    posting_error = models.TextField(null=True, blank=True)
    created_by = models.CharField(max_length=80, default="agent-2-finance-close")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(event_type__in=MANUAL_EVENT_TYPES), name="acct_manual_catalogue"),
            models.CheckConstraint(condition=~Q(event_type__in=["tax.assessed", "tax.paid"]) | (Q(evidence_ref__isnull=False) & ~Q(evidence_ref="")), name="acct_manual_tax_evidence"),
            models.CheckConstraint(condition=~Q(event_type="owner.funds_moved") | Q(payload__funds_type__in=["capital", "drawings", "loan"]), name="acct_manual_funds_type"),
            models.CheckConstraint(condition=~Q(basis="estimate") | Q(payload__has_key="basis_note"), name="acct_manual_estimate_basis"),
        ]


class ClearingCause(models.Model):
    """Named explanation for a still-open clearing debit; never changes the journal."""

    line = models.OneToOneField(JournalLine, on_delete=models.PROTECT)
    cause = models.CharField(max_length=255)
    evidence_ref = models.CharField(max_length=255)
    recorded_by = models.CharField(max_length=120)
    recorded_at = models.DateTimeField(auto_now_add=True)


class CloseRun(models.Model):
    period = models.CharField(max_length=7)
    dataset_kind = models.CharField(max_length=6, choices=DatasetKind.choices)
    runner = models.CharField(max_length=120)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    elapsed_seconds = models.DecimalField(max_digits=12, decimal_places=4)
    status = models.CharField(max_length=12)
    gate_results = models.JSONField(default=list)
    remaining_open = models.JSONField(default=list)
    signature = models.CharField(max_length=64)


class CloseAudit(models.Model):
    period = models.CharField(max_length=7)
    action = models.CharField(max_length=12)
    actor = models.CharField(max_length=120)
    reason = models.TextField()
    close_run = models.ForeignKey(CloseRun, null=True, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)
