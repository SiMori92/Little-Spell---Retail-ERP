"""Slice A operational facts. Monetary amounts are integer transaction minor units."""

from django.db import models
from django.db.models import Q

from core.models import DatasetKind


class Provenance(models.Model):
    source_filename = models.CharField(max_length=255)
    dataset_kind = models.CharField(max_length=6, choices=DatasetKind.choices)

    class Meta:
        abstract = True


class Product(models.Model):
    sku = models.CharField(max_length=20, primary_key=True)
    name = models.CharField(max_length=100)
    uom = models.CharField(max_length=2, default="PK")
    pack_qty = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(uom="PK"), name="ops_product_pack_uom"),
            models.CheckConstraint(condition=Q(pack_qty__isnull=True) | Q(pack_qty__gt=0), name="ops_product_positive_pack_qty"),
        ]


class Channel(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=100)


class Order(Provenance):
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT)
    channel_order_id = models.CharField(max_length=64)
    order_date = models.DateField()
    currency = models.CharField(max_length=3)
    coupon_code = models.CharField(max_length=40, blank=True, default="")
    discount_funded_by = models.CharField(max_length=8)
    gross_minor = models.BigIntegerField()
    discount_minor = models.BigIntegerField()
    buyer_paid_minor = models.BigIntegerField()
    shipping_minor = models.BigIntegerField()
    shipping_discount_minor = models.BigIntegerField()
    tax_remitted_by_platform_minor = models.BigIntegerField(default=0)
    dest_country = models.CharField(max_length=2)
    status = models.CharField(max_length=20, default="placed")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["channel", "channel_order_id"], name="ops_order_channel_key"),
            models.CheckConstraint(condition=Q(discount_funded_by__in=["seller", "platform", "none"]), name="ops_order_funder_allowed"),
            models.CheckConstraint(condition=(Q(discount_minor=0, discount_funded_by="none") | Q(discount_minor__gt=0, discount_funded_by__in=["seller", "platform"])), name="ops_order_funder_matches_discount"),
            models.CheckConstraint(condition=Q(gross_minor__gte=0, discount_minor__gte=0, buyer_paid_minor__gte=0, shipping_minor__gte=0, shipping_discount_minor__gte=0, tax_remitted_by_platform_minor__gte=0), name="ops_order_nonnegative_money"),
            models.CheckConstraint(condition=Q(gross_minor=models.F("buyer_paid_minor") + models.F("discount_minor")), name="ops_order_gross_identity"),
        ]


class OrderLine(Provenance):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    platform_transaction_id = models.CharField(max_length=64, unique=True)
    listing_id = models.CharField(max_length=64, blank=True, default="")
    line_index = models.PositiveIntegerField()
    qty_packs = models.PositiveIntegerField()
    unit_price_minor = models.BigIntegerField()
    line_discount_minor = models.BigIntegerField()
    item_total_minor = models.BigIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(qty_packs__gt=0), name="ops_line_positive_qty"),
            models.CheckConstraint(condition=Q(unit_price_minor__gte=0, line_discount_minor__gte=0, item_total_minor__gte=0), name="ops_line_nonnegative_money"),
            models.CheckConstraint(condition=Q(item_total_minor=models.F("qty_packs") * models.F("unit_price_minor") - models.F("line_discount_minor")), name="ops_line_total_identity"),
        ]


class Shipment(Provenance):
    order = models.OneToOneField(Order, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, default="pending")
    ship_date = models.DateField(null=True, blank=True)
    tracking_ref = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        constraints = [models.CheckConstraint(condition=~Q(status="dispatched") | Q(ship_date__isnull=False), name="ops_dispatched_has_ship_date")]


class InventoryMove(Provenance):
    class Kind(models.TextChoices):
        OPENING = "opening"
        RECEIVED = "received"
        SOLD = "sold"
        WRITTEN_OFF = "written_off"
        RETURNED = "returned"
        ADJUSTED = "adjusted"

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    qty_delta_packs = models.IntegerField()
    value_delta_twd = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    occurred_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=255, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~Q(qty_delta_packs=0) | Q(kind="opening", value_delta_twd=0), name="ops_move_nonzero"),
            models.CheckConstraint(condition=(Q(kind="opening", qty_delta_packs__gte=0) | Q(kind__in=["received", "returned"], qty_delta_packs__gt=0) | Q(kind__in=["sold", "written_off"], qty_delta_packs__lt=0) | Q(kind="adjusted", qty_delta_packs__lt=0)), name="ops_move_sign_discipline"),
            models.CheckConstraint(condition=Q(value_delta_twd__isnull=True) | (Q(qty_delta_packs__gt=0, value_delta_twd__gte=0) | Q(qty_delta_packs__lt=0, value_delta_twd__lte=0) | Q(kind="opening", qty_delta_packs=0, value_delta_twd=0)), name="ops_move_value_sign"),
        ]


OPS_EVENT_TYPES = (
    "order.placed", "order.fees_assessed", "order.shipped", "order.cogs_relieved",
    "order.ship_cost_accrued", "order.ship_cost_invoiced", "order.duty_incurred",
    "order.duty_invoiced", "order.reprint_issued", "order.cancelled", "order.refunded",
    "payment.received", "payment.refunded", "settlement.received", "settlement.reversed",
    "po.in_transit", "po.received", "po.landed_cost_adjusted", "po.paid",
    "inventory.adjusted", "inventory.opening_counted", "cost.recorded",
)


class LedgerEvent(Provenance):
    event_type = models.CharField(max_length=40, choices=[(x, x) for x in OPS_EVENT_TYPES])
    entity_table = models.CharField(max_length=64)
    entity_id = models.BigIntegerField()
    occurred_at = models.DateTimeField()
    amount_minor = models.BigIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, null=True, blank=True)
    payload = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=255, unique=True)
    posted_entry_id = models.BigIntegerField(null=True, blank=True)  # Slice B links this.
    posting_error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(event_type__in=OPS_EVENT_TYPES), name="ops_event_catalogue_only"),
            models.CheckConstraint(condition=Q(amount_minor__isnull=True) | Q(amount_minor__gte=0), name="ops_event_nonnegative_amount"),
        ]
        indexes = [models.Index(fields=["posted_entry_id"], name="ops_event_unposted_idx")]


class EtsyStatementPeriod(Provenance):
    period = models.CharField(max_length=7, unique=True)
    multiset_digest = models.CharField(max_length=64)
    source_sha256 = models.CharField(max_length=64)
    row_count = models.PositiveIntegerField()


class EtsyStatementRow(Provenance):
    period = models.ForeignKey(EtsyStatementPeriod, on_delete=models.PROTECT)
    row_key = models.CharField(max_length=100, unique=True)
    row_type = models.CharField(max_length=40)
    occurred_at = models.DateTimeField()
    order_ref = models.CharField(max_length=64, blank=True, default="")
    listing_ref = models.CharField(max_length=64, blank=True, default="")
    currency = models.CharField(max_length=3)
    amount_minor = models.BigIntegerField(null=True, blank=True)
    fee_minor = models.BigIntegerField(null=True, blank=True)
    net_minor = models.BigIntegerField()

    class Meta:
        constraints = [models.CheckConstraint(condition=(Q(amount_minor__isnull=True, fee_minor__isnull=False) | Q(amount_minor__isnull=False, fee_minor__isnull=True)), name="ops_stmt_one_money_column")]


class Receipt(Provenance):
    """One evidenced TWD receipt; its evidence reference is the natural key."""

    occurred_on = models.DateField()
    category = models.CharField(max_length=32)
    amount_twd = models.DecimalField(max_digits=18, decimal_places=4)
    settled_via = models.CharField(max_length=8)
    evidence_ref = models.CharField(max_length=255)
    description = models.CharField(max_length=255)
    channel_attribution = models.CharField(max_length=16, blank=True, default="")
    bank_account = models.CharField(max_length=4, blank=True, default="")
    idempotency_key = models.CharField(max_length=100, unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset_kind", "evidence_ref"], name="ops_receipt_evidence_key"),
            models.CheckConstraint(condition=Q(amount_twd__gt=0), name="ops_receipt_positive_amount"),
        ]


class StockCount(Provenance):
    """One physical count session, documented by one evidence reference."""

    counted_at = models.DateField()
    evidence_ref = models.CharField(max_length=255)
    kind = models.CharField(max_length=10, choices=[("opening", "Opening"), ("adjustment", "Adjustment")])
    total_value_twd = models.DecimalField(max_digits=18, decimal_places=4)
    idempotency_key = models.CharField(max_length=100, unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset_kind", "evidence_ref"], name="ops_count_evidence_key"),
        ]


class StockCountLine(Provenance):
    count = models.ForeignKey(StockCount, related_name="lines", on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty_packs = models.PositiveIntegerField()
    agreed_unit_cost_twd = models.DecimalField(max_digits=18, decimal_places=4)
    line_value_twd = models.DecimalField(max_digits=18, decimal_places=4)
    condition = models.CharField(max_length=20, choices=[("sellable", "Sellable"),
                                                          ("damaged_unsellable", "Damaged, unsellable")])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["count", "product"], name="ops_count_one_line_per_sku"),
            models.CheckConstraint(condition=Q(agreed_unit_cost_twd__gte=0, line_value_twd__gte=0),
                                   name="ops_count_nonnegative_value"),
        ]


class OpsPeriod(models.Model):
    """Ops event admission lock; the journal lock belongs to Slice B."""

    period = models.CharField(max_length=7, primary_key=True)
    status = models.CharField(max_length=6, default="OPEN")

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(status__in=["OPEN", "CLOSED"]), name="ops_period_status")]


class OnHand(models.Model):
    """Read-only view; never stores on-hand quantities."""

    sku = models.CharField(max_length=20, primary_key=True)
    qty_packs = models.BigIntegerField()

    class Meta:
        managed = False
        db_table = "ops_on_hand"
