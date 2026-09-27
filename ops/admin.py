"""Operational records are inspected here; intake files are the only write path."""

from django.contrib import admin

from ops.models import (Channel, EtsyStatementPeriod, EtsyStatementRow, IgDeal,
                        IgDealStatus, InventoryMove, LedgerEvent, OnHand, OpsPeriod, Order, OrderLine, Product,
                        ProductComplianceChange, Receipt, Shipment, StockCount,
                        StockCountLine, Supplier, SupplierChange)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class DeclarationOnFileFilter(admin.SimpleListFilter):
    title = "declaration on file"
    parameter_name = "declaration_on_file"

    def lookups(self, request, model_admin):
        return (("yes", "Yes"), ("no", "No"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(declaration_ref="")
        if self.value() == "no":
            return queryset.filter(declaration_ref="")
        return queryset


class IngredientUnknownFilter(admin.SimpleListFilter):
    title = "ingredient_ref = UNKNOWN"
    parameter_name = "ingredient_unknown"

    def lookups(self, request, model_admin):
        return (("yes", "Yes"), ("no", "No"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(ingredient_ref="UNKNOWN")
        if self.value() == "no":
            return queryset.exclude(ingredient_ref="UNKNOWN")
        return queryset


@admin.register(Product)
class ProductAdmin(ReadOnlyAdmin):
    list_display = ("sku", "name", "uom", "pack_qty", "supplier", "ingredient_ref")
    list_filter = (IngredientUnknownFilter,)
    search_fields = ("sku", "name")


@admin.register(Supplier)
class SupplierAdmin(ReadOnlyAdmin):
    list_display = ("supplier_ref", "legal_name", "country", "currency",
                    "can_invoice_to_tax_id", "declaration_ref", "dataset_kind")
    list_filter = ("country", "can_invoice_to_tax_id", DeclarationOnFileFilter)
    search_fields = ("supplier_ref", "legal_name")


@admin.register(SupplierChange)
class SupplierChangeAdmin(ReadOnlyAdmin):
    list_display = ("supplier_ref", "field", "old", "new", "source_filename", "dataset_kind")
    list_filter = ("field", "dataset_kind")
    search_fields = ("supplier_ref", "source_filename", "evidence_ref")


@admin.register(ProductComplianceChange)
class ProductComplianceChangeAdmin(ReadOnlyAdmin):
    list_display = ("sku", "field", "old", "new", "source_filename", "dataset_kind")
    list_filter = ("field", "dataset_kind")
    search_fields = ("sku", "source_filename", "evidence_ref")


@admin.register(IgDeal)
class IgDealAdmin(ReadOnlyAdmin):
    list_display = ("deal_id", "line_no", "customer_ref", "status", "enquiry_at",
                    "product", "consent_marketing", "dataset_kind")
    list_filter = ("status", ("enquiry_at", admin.DateFieldListFilter), "lost_reason",
                   "consent_marketing", "dataset_kind")
    search_fields = ("deal_id", "customer_ref", "wallet_txn_id", "evidence_ref")


@admin.register(IgDealStatus)
class IgDealStatusAdmin(ReadOnlyAdmin):
    list_display = ("deal_id", "status", "effective_on", "source_filename", "dataset_kind")
    list_filter = ("status", "effective_on", "dataset_kind")
    search_fields = ("deal_id", "source_filename")


@admin.register(Channel)
class ChannelAdmin(ReadOnlyAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(Order)
class OrderAdmin(ReadOnlyAdmin):
    list_display = ("channel_order_id", "channel", "order_date", "status", "currency", "dataset_kind")
    list_filter = ("dataset_kind", "status", "channel", "order_date")
    search_fields = ("channel_order_id", "channel__code")


@admin.register(OrderLine)
class OrderLineAdmin(ReadOnlyAdmin):
    list_display = ("platform_transaction_id", "order_id", "product_id", "qty_packs", "dataset_kind")
    list_filter = ("dataset_kind",)
    search_fields = ("platform_transaction_id", "order__channel_order_id", "product__sku")


@admin.register(Shipment)
class ShipmentAdmin(ReadOnlyAdmin):
    list_display = ("order_id", "status", "ship_date", "dataset_kind")
    list_filter = ("dataset_kind", "status", "ship_date")
    search_fields = ("order__channel_order_id", "tracking_ref")


@admin.register(InventoryMove)
class InventoryMoveAdmin(ReadOnlyAdmin):
    list_display = ("product_id", "kind", "qty_delta_packs", "value_delta_twd", "dataset_kind")
    list_filter = ("dataset_kind", "kind")
    search_fields = ("product__sku", "idempotency_key")


@admin.register(LedgerEvent)
class LedgerEventAdmin(ReadOnlyAdmin):
    list_display = ("event_type", "entity_table", "entity_id", "occurred_at", "posted_entry_id", "dataset_kind")
    list_filter = ("dataset_kind", "event_type")
    search_fields = ("event_type", "idempotency_key", "entity_table")


@admin.register(EtsyStatementPeriod)
class EtsyStatementPeriodAdmin(ReadOnlyAdmin):
    list_display = ("period", "row_count", "dataset_kind", "source_filename")
    list_filter = ("dataset_kind",)
    search_fields = ("period",)


@admin.register(EtsyStatementRow)
class EtsyStatementRowAdmin(ReadOnlyAdmin):
    list_display = ("row_key", "row_type", "period", "order_ref", "net_minor", "dataset_kind")
    list_filter = ("dataset_kind", "row_type")
    search_fields = ("row_key", "order_ref", "period__period")


@admin.register(Receipt)
class ReceiptAdmin(ReadOnlyAdmin):
    list_display = ("occurred_on", "category", "amount_twd", "settled_via", "dataset_kind")
    list_filter = ("dataset_kind", "category", "settled_via")
    search_fields = ("evidence_ref", "idempotency_key")


@admin.register(StockCount)
class StockCountAdmin(ReadOnlyAdmin):
    list_display = ("counted_at", "kind", "total_value_twd", "dataset_kind")
    list_filter = ("dataset_kind", "kind", "counted_at")
    search_fields = ("evidence_ref", "idempotency_key")


@admin.register(StockCountLine)
class StockCountLineAdmin(ReadOnlyAdmin):
    list_display = ("count_id", "product_id", "qty_packs", "condition", "dataset_kind")
    list_filter = ("dataset_kind", "condition")
    search_fields = ("product__sku", "count__evidence_ref")


@admin.register(OpsPeriod)
class OpsPeriodAdmin(ReadOnlyAdmin):
    list_display = ("period", "status")
    list_filter = ("status",)
    search_fields = ("period",)


@admin.register(OnHand)
class OnHandAdmin(ReadOnlyAdmin):
    list_display = ("sku", "qty_packs")
    search_fields = ("sku",)
