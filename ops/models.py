"""Slice A operational facts. Monetary amounts are integer transaction minor units."""

from django.db import models
from django.db.models import Q

from core.models import DatasetKind


class Provenance(models.Model):
    source_filename = models.CharField(max_length=255)
    dataset_kind = models.CharField(max_length=6, choices=DatasetKind.choices)

    class Meta:
        abstract = True


class Supplier(Provenance):
    supplier_ref = models.CharField(max_length=7)
    legal_name = models.CharField(max_length=255)
    country = models.CharField(max_length=2)
    currency = models.CharField(max_length=3)
    default_incoterm = models.CharField(max_length=3)
    payment_terms = models.CharField(max_length=255)
    can_invoice_to_tax_id = models.CharField(max_length=7)
    declaration_ref = models.CharField(max_length=255, blank=True, default="")
    evidence_ref = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset_kind", "supplier_ref"],
                                    name="ops_supplier_dataset_ref"),
            models.CheckConstraint(
                condition=(Q(declaration_ref="") |
                           (Q(declaration_ref__startswith="compliance/suppliers/") &
                            ~Q(declaration_ref="compliance/suppliers/"))),
                name="ops_supplier_declaration_ref_shape",
            ),
        ]


PRODUCT_TYPES = ("sellable", "packaging")
NOT_APPLICABLE = "NOT_APPLICABLE"


class Product(models.Model):
    sku = models.CharField(max_length=20, primary_key=True)
    name = models.CharField(max_length=100)
    uom = models.CharField(max_length=2, default="PC")
    pieces_per_sale_unit = models.PositiveIntegerField()
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.PROTECT)
    ingredient_ref = models.CharField(max_length=255, default="UNKNOWN")
    product_type = models.CharField(max_length=9, default="sellable",
                                    choices=[(value, value) for value in PRODUCT_TYPES])

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(uom="PC"), name="ops_product_piece_uom"),
            models.CheckConstraint(condition=Q(pieces_per_sale_unit__gte=1),
                                   name="ops_product_positive_pieces_per_sale_unit"),
            models.CheckConstraint(condition=Q(product_type__in=PRODUCT_TYPES),
                                   name="ops_product_type_allowed"),
            # G-1 I-5: packaging carries NOT_APPLICABLE, and only packaging may.
            models.CheckConstraint(
                condition=(
                    (Q(product_type="sellable") &
                     (Q(ingredient_ref="UNKNOWN") |
                      (Q(ingredient_ref__startswith="compliance/suppliers/") &
                       ~Q(ingredient_ref="compliance/suppliers/")))) |
                    Q(product_type="packaging", ingredient_ref=NOT_APPLICABLE)
                ),
                name="ops_product_ingredient_ref_shape",
            ),
        ]


class SupplierChange(Provenance):
    supplier_ref = models.CharField(max_length=7)
    field = models.CharField(max_length=32)
    old = models.TextField(blank=True, default="")
    new = models.TextField(blank=True, default="")
    evidence_ref = models.CharField(max_length=255)


class ProductComplianceChange(Provenance):
    sku = models.CharField(max_length=20)
    field = models.CharField(max_length=32)
    old = models.TextField(blank=True, default="")
    new = models.TextField(blank=True, default="")
    evidence_ref = models.CharField(max_length=255)


IG_STATUSES = ("enquiry", "quoted", "paid", "shipped", "followed_up", "lost")


class IgDeal(Provenance):
    deal_id = models.CharField(max_length=13)
    line_no = models.PositiveIntegerField()
    customer_ref = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=[(value, value) for value in IG_STATUSES])
    enquiry_at = models.DateField()
    quoted_at = models.DateField(null=True, blank=True)
    quote_twd = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    follow_up_on = models.DateField(null=True, blank=True)
    lost_reason = models.CharField(max_length=24, blank=True, default="")
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.PROTECT)
    qty_sale_units = models.PositiveIntegerField(null=True, blank=True)
    unit_price_twd = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    shipping_charged_twd = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    ship_country = models.CharField(max_length=2, blank=True, default="")
    paid_at = models.DateField(null=True, blank=True)
    wallet_txn_id = models.CharField(max_length=100, blank=True, default="")
    ship_date = models.DateField(null=True, blank=True)
    consent_marketing = models.CharField(max_length=3, blank=True, default="")
    journey_sent = models.CharField(max_length=4, default="none")
    evidence_ref = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset_kind", "deal_id", "line_no"],
                                    name="ops_ig_deal_dataset_line"),
            models.CheckConstraint(condition=Q(line_no__gte=1), name="ops_ig_deal_line_positive"),
            models.CheckConstraint(condition=Q(quote_twd__isnull=True) | Q(quote_twd__gt=0),
                                   name="ops_ig_deal_quote_positive"),
            models.CheckConstraint(condition=Q(qty_sale_units__isnull=True) | Q(qty_sale_units__gt=0),
                                   name="ops_ig_deal_qty_positive"),
            models.CheckConstraint(condition=Q(unit_price_twd__isnull=True) | Q(unit_price_twd__gt=0),
                                   name="ops_ig_deal_price_positive"),
            models.CheckConstraint(condition=Q(shipping_charged_twd__isnull=True) |
                                   Q(shipping_charged_twd__gte=0), name="ops_ig_deal_shipping_nonnegative"),
            models.CheckConstraint(condition=Q(consent_marketing__in=["", "yes", "no"]),
                                   name="ops_ig_deal_consent_allowed"),
            models.CheckConstraint(condition=Q(journey_sent__in=["none", "d0", "d10", "d30"]),
                                   name="ops_ig_deal_journey_allowed"),
            models.CheckConstraint(
                condition=(
                    (Q(quoted_at__isnull=True) | Q(quoted_at__gte=models.F("enquiry_at"))) &
                    (Q(paid_at__isnull=True) | Q(paid_at__gte=models.F("enquiry_at"))) &
                    (Q(ship_date__isnull=True) | Q(ship_date__gte=models.F("enquiry_at"))) &
                    (Q(quoted_at__isnull=True) | Q(paid_at__isnull=True) |
                     Q(paid_at__gte=models.F("quoted_at"))) &
                    (Q(quoted_at__isnull=True) | Q(ship_date__isnull=True) |
                     Q(ship_date__gte=models.F("quoted_at"))) &
                    (Q(paid_at__isnull=True) | Q(ship_date__isnull=True) |
                     Q(ship_date__gte=models.F("paid_at"))) &
                    (Q(follow_up_on__isnull=True) |
                     Q(follow_up_on__gte=models.F("enquiry_at")))
                ),
                name="ops_igdeal_date_order",
            ),
        ]


class IgDealStatus(Provenance):
    deal_id = models.CharField(max_length=13)
    status = models.CharField(max_length=16, choices=[(value, value) for value in IG_STATUSES])
    effective_on = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset_kind", "deal_id", "status"],
                                    name="ops_ig_status_once"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise RuntimeError("Instagram deal status history is append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Instagram deal status history is append-only")


PO_STATUSES = ("draft", "sent", "acknowledged", "cancelled")
PO_INCOTERMS = ("EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF")


class PurchaseOrder(Provenance):
    """A commitment to a supplier. G-1 posts nothing; receiving is G-2."""

    po_number = models.CharField(max_length=11)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    po_date = models.DateField()
    target_delivery_date = models.DateField()
    currency = models.CharField(max_length=3)
    payment_terms = models.CharField(max_length=255)
    incoterm = models.CharField(max_length=3, choices=[(value, value) for value in PO_INCOTERMS])
    quote_ref = models.CharField(max_length=255)
    status = models.CharField(max_length=12, choices=[(value, value) for value in PO_STATUSES])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset_kind", "po_number"], name="ops_po_dataset_number"),
            models.CheckConstraint(condition=Q(po_number__regex=r"^PO-[0-9]{4}-[0-9]{3}$"),
                                   name="ops_po_number_shape"),
            models.CheckConstraint(condition=Q(status__in=PO_STATUSES), name="ops_po_status_allowed"),
            models.CheckConstraint(condition=Q(incoterm__in=PO_INCOTERMS), name="ops_po_incoterm_allowed"),
            # I-7: TWD only until the FX ruling (Agent 2 R-2.6, IFRIC 22) exists.
            models.CheckConstraint(condition=Q(currency="TWD"), name="ops_po_currency_twd"),
            models.CheckConstraint(condition=~Q(quote_ref=""), name="ops_po_quote_ref_required"),
            models.CheckConstraint(condition=~Q(payment_terms=""), name="ops_po_payment_terms_required"),
            models.CheckConstraint(condition=Q(target_delivery_date__gte=models.F("po_date")),
                                   name="ops_po_target_after_po_date"),
        ]


class PurchaseOrderLine(Provenance):
    """One SKU on a PO. Quantities are whole pieces; prices are per piece (F.6)."""

    po = models.ForeignKey(PurchaseOrder, related_name="lines", on_delete=models.PROTECT)
    line_no = models.PositiveIntegerField()
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty_pieces = models.PositiveIntegerField()
    unit_price_twd = models.DecimalField(max_digits=18, decimal_places=4)
    setup_charge_twd = models.DecimalField(max_digits=18, decimal_places=4)
    line_total_twd = models.DecimalField(max_digits=18, decimal_places=4)
    min_order_qty_pieces = models.PositiveIntegerField(null=True, blank=True)
    artwork_ref = models.CharField(max_length=255, blank=True, default="")
    evidence_ref = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["po", "line_no"], name="ops_po_line_once"),
            models.CheckConstraint(condition=Q(line_no__gte=1), name="ops_po_line_positive"),
            models.CheckConstraint(condition=Q(qty_pieces__gt=0), name="ops_po_line_positive_pieces"),
            models.CheckConstraint(condition=Q(unit_price_twd__gt=0), name="ops_po_line_positive_price"),
            models.CheckConstraint(condition=Q(setup_charge_twd__gte=0), name="ops_po_line_setup_nonnegative"),
            # I-3: exact, per line. Integer pieces times a 4dp price is exact in numeric.
            models.CheckConstraint(
                condition=Q(line_total_twd=models.F("qty_pieces") * models.F("unit_price_twd")
                            + models.F("setup_charge_twd")),
                name="ops_po_line_total_identity",
            ),
            models.CheckConstraint(
                condition=Q(min_order_qty_pieces__isnull=True) |
                          Q(qty_pieces__gte=models.F("min_order_qty_pieces")),
                name="ops_po_line_meets_moq",
            ),
            models.CheckConstraint(condition=~Q(evidence_ref=""), name="ops_po_line_evidence_required"),
        ]


class PurchaseOrderStatus(Provenance):
    po_number = models.CharField(max_length=11)
    status = models.CharField(max_length=12, choices=[(value, value) for value in PO_STATUSES])
    effective_on = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset_kind", "po_number", "status"],
                                    name="ops_po_status_once"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise RuntimeError("purchase order status history is append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("purchase order status history is append-only")


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
    qty_sale_units = models.PositiveIntegerField()
    unit_price_minor = models.BigIntegerField()
    line_discount_minor = models.BigIntegerField()
    item_total_minor = models.BigIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(qty_sale_units__gt=0), name="ops_line_positive_qty"),
            models.CheckConstraint(condition=Q(unit_price_minor__gte=0, line_discount_minor__gte=0, item_total_minor__gte=0), name="ops_line_nonnegative_money"),
            models.CheckConstraint(condition=Q(item_total_minor=models.F("qty_sale_units") * models.F("unit_price_minor") - models.F("line_discount_minor")), name="ops_line_total_identity"),
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
    qty_delta_pieces = models.IntegerField()
    value_delta_twd = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    occurred_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=255, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~Q(qty_delta_pieces=0) | Q(kind="opening", value_delta_twd=0), name="ops_move_nonzero"),
            models.CheckConstraint(condition=(Q(kind="opening", qty_delta_pieces__gte=0) | Q(kind__in=["received", "returned"], qty_delta_pieces__gt=0) | Q(kind__in=["sold", "written_off"], qty_delta_pieces__lt=0) | Q(kind="adjusted", qty_delta_pieces__lt=0)), name="ops_move_sign_discipline"),
            models.CheckConstraint(condition=Q(value_delta_twd__isnull=True) | (Q(qty_delta_pieces__gt=0, value_delta_twd__gte=0) | Q(qty_delta_pieces__lt=0, value_delta_twd__lte=0) | Q(kind="opening", qty_delta_pieces=0, value_delta_twd=0)), name="ops_move_value_sign"),
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
    qty_pieces = models.PositiveIntegerField()
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
    qty_pieces = models.BigIntegerField()

    class Meta:
        managed = False
        db_table = "ops_on_hand"
