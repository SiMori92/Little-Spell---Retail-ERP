# Generated for Slice G-3 on 2026-09-27.

import django.db.models.deletion
from django.db import migrations, models
import importlib

G2 = importlib.import_module("ops.migrations.0013_goods_receipt_supplier_invoice")


PAYMENT_APPEND_ONLY_SQL = """
CREATE TRIGGER ops_supplierpayment_append_only
    BEFORE UPDATE OR DELETE ON ops_supplierpayment
    FOR EACH ROW EXECUTE FUNCTION ops_purchase_document_append_only();
"""

PAYMENT_APPEND_ONLY_REVERSE_SQL = """
DROP TRIGGER IF EXISTS ops_supplierpayment_append_only ON ops_supplierpayment;
"""

PO_FORWARD_ONLY_SQL = """
CREATE OR REPLACE FUNCTION ops_purchaseorder_forward_only() RETURNS trigger AS $$
DECLARE
    open_deposit numeric(18,4);
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ops_purchaseorder % is never deleted; cancel it', OLD.po_number;
    END IF;
    IF NEW.currency IS DISTINCT FROM (SELECT currency FROM ops_supplier WHERE id = NEW.supplier_id) THEN
        RAISE EXCEPTION 'ops_purchaseorder % currency must equal the supplier currency', NEW.po_number;
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'ops_purchaseorder % is created as draft; later statuses are forward moves', NEW.po_number;
        END IF;
    ELSE
        IF OLD.status IN ('cancelled', 'closed') THEN
            RAISE EXCEPTION 'ops_purchaseorder % is %; nothing leaves %', OLD.po_number, OLD.status, OLD.status;
        END IF;
        IF OLD.status IN ('received', 'short_closed') AND NEW.status <> 'closed' THEN
            RAISE EXCEPTION 'ops_purchaseorder % is %; it may move only to closed', OLD.po_number, OLD.status;
        END IF;
        IF NEW.po_number IS DISTINCT FROM OLD.po_number OR NEW.dataset_kind IS DISTINCT FROM OLD.dataset_kind THEN
            RAISE EXCEPTION 'ops_purchaseorder po_number and dataset_kind cannot change';
        END IF;
        IF NEW.status <> OLD.status AND NOT (
            (OLD.status = 'draft' AND NEW.status IN ('sent', 'cancelled')) OR
            (OLD.status = 'sent' AND NEW.status IN ('acknowledged', 'cancelled', 'received', 'short_closed')) OR
            (OLD.status = 'acknowledged' AND NEW.status IN ('cancelled', 'received', 'short_closed')) OR
            (OLD.status IN ('received', 'short_closed') AND NEW.status = 'closed')
        ) THEN
            RAISE EXCEPTION 'ops_purchaseorder % status cannot move from % to %', OLD.po_number, OLD.status, NEW.status;
        END IF;
        IF OLD.status IN ('sent', 'acknowledged') AND (
            NEW.supplier_id IS DISTINCT FROM OLD.supplier_id OR NEW.currency IS DISTINCT FROM OLD.currency OR
            NEW.quote_ref IS DISTINCT FROM OLD.quote_ref
        ) THEN
            RAISE EXCEPTION 'ops_purchaseorder % supplier, currency and quote_ref are frozen once sent', NEW.po_number;
        END IF;
        IF NEW.status = 'cancelled' AND EXISTS (SELECT 1 FROM ops_goodsreceipt WHERE po_id = NEW.id) THEN
            RAISE EXCEPTION 'ops_purchaseorder % has goods received and cannot be cancelled', NEW.po_number;
        END IF;
        IF NEW.status IN ('received', 'short_closed') THEN
            IF EXISTS (
                SELECT 1 FROM ops_purchaseorderline l LEFT JOIN ops_goodsreceiptline r ON r.po_line_id = l.id
                WHERE l.po_id = NEW.id AND r.id IS NULL
            ) THEN
                RAISE EXCEPTION 'ops_purchaseorder % cannot be % until every line is received', NEW.po_number, NEW.status;
            END IF;
            IF (NEW.status = 'short_closed') IS DISTINCT FROM EXISTS (
                SELECT 1 FROM ops_goodsreceiptline r JOIN ops_purchaseorderline l ON r.po_line_id = l.id
                WHERE l.po_id = NEW.id AND r.short_close
            ) THEN
                RAISE EXCEPTION 'ops_purchaseorder % is short_closed exactly when a line was short-closed', NEW.po_number;
            END IF;
        END IF;
        IF NEW.status = 'closed' THEN
            SELECT COALESCE(SUM(CASE p.payment_kind WHEN 'deposit' THEN p.amount_twd
                                WHEN 'deposit_refund' THEN -p.amount_twd
                                WHEN 'deposit_forfeit' THEN -p.amount_twd ELSE 0 END), 0)
                   - COALESCE((SELECT SUM((e.payload->>'deposit_applied_twd')::numeric)
                               FROM ops_ledgerevent e WHERE e.event_type = 'po.received'
                               AND e.dataset_kind = NEW.dataset_kind AND e.payload->>'po_number' = NEW.po_number
                               AND e.posted_entry_id IS NOT NULL AND e.posting_error IS NULL), 0)
            INTO open_deposit FROM ops_supplierpayment p WHERE p.po_id = NEW.id;
            IF open_deposit <> 0 THEN
                RAISE EXCEPTION 'ops_purchaseorder % cannot close with 1266 balance %', NEW.po_number, open_deposit;
            END IF;
            IF EXISTS (
                SELECT 1 FROM ops_supplierinvoice i
                WHERE i.po_id = NEW.id AND i.invoice_total_twd
                    - COALESCE((SELECT (e.payload->>'deposit_applied_twd')::numeric
                                FROM ops_ledgerevent e WHERE e.event_type = 'po.received'
                                AND e.dataset_kind = NEW.dataset_kind AND e.payload->>'invoice_no' = i.invoice_no
                                AND e.posted_entry_id IS NOT NULL AND e.posting_error IS NULL LIMIT 1), 0)
                    - COALESCE((SELECT SUM(p.amount_twd) FROM ops_supplierpayment p
                                WHERE p.invoice_id = i.id AND p.payment_kind = 'balance'), 0) <> 0
            ) THEN
                RAISE EXCEPTION 'ops_purchaseorder % cannot close until every supplier invoice is fully paid', NEW.po_number;
            END IF;
        END IF;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM ops_purchaseorderstatus
        WHERE dataset_kind = NEW.dataset_kind AND po_number = NEW.po_number AND status = NEW.status
    ) THEN
        RAISE EXCEPTION 'ops_purchaseorder % status % requires its PurchaseOrderStatus history row', NEW.po_number, NEW.status;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def refuse_reverse(apps, schema_editor):
    Payment = apps.get_model("ops", "SupplierPayment")
    PurchaseOrder = apps.get_model("ops", "PurchaseOrder")
    SupplierInvoice = apps.get_model("ops", "SupplierInvoice")
    if Payment.objects.exists() or PurchaseOrder.objects.filter(status="closed").exists() or \
            SupplierInvoice.objects.exclude(deposit_applied_twd=0).exists():
        raise RuntimeError("Reversing G-3 refused: supplier-payment/deposit facts exist")


class Migration(migrations.Migration):

    dependencies = [("ops", "0013_goods_receipt_supplier_invoice")]

    operations = [
        migrations.CreateModel(
            name="SupplierPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False,
                                           verbose_name="ID")),
                ("source_filename", models.CharField(max_length=255)),
                ("dataset_kind", models.CharField(choices=[("SAMPLE", "Sample data — not actuals"),
                                                            ("ACTUAL", "Actual data")], max_length=6)),
                ("payment_ref", models.CharField(max_length=32)),
                ("paid_on", models.DateField()),
                ("payment_kind", models.CharField(choices=[("deposit", "deposit"),
                                                            ("balance", "balance"),
                                                            ("deposit_refund", "deposit_refund"),
                                                            ("deposit_forfeit", "deposit_forfeit")],
                                                  max_length=16)),
                ("amount_twd", models.DecimalField(decimal_places=4, max_digits=18)),
                ("bank_account", models.CharField(max_length=4)),
                ("bank_ref", models.CharField(blank=True, default="", max_length=255)),
                ("evidence_ref", models.CharField(max_length=255)),
                ("invoice", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                               related_name="payments", to="ops.supplierinvoice")),
                ("po", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                          related_name="payments", to="ops.purchaseorder")),
                ("supplier", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                related_name="payments", to="ops.supplier")),
            ],
        ),
        migrations.RemoveConstraint(model_name="supplierinvoice", name="ops_invoice_no_deposit_before_g3"),
        migrations.RemoveConstraint(model_name="purchaseorder", name="ops_po_status_allowed"),
        migrations.AlterField(model_name="purchaseorder", name="status",
                              field=models.CharField(choices=[("draft", "draft"), ("sent", "sent"),
                                                             ("acknowledged", "acknowledged"),
                                                             ("cancelled", "cancelled"),
                                                             ("received", "received"),
                                                             ("short_closed", "short_closed"),
                                                             ("closed", "closed")], max_length=12)),
        migrations.AlterField(model_name="purchaseorderstatus", name="status",
                              field=models.CharField(choices=[("draft", "draft"), ("sent", "sent"),
                                                             ("acknowledged", "acknowledged"),
                                                             ("cancelled", "cancelled"),
                                                             ("received", "received"),
                                                             ("short_closed", "short_closed"),
                                                             ("closed", "closed")], max_length=12)),
        migrations.AddConstraint(model_name="purchaseorder", constraint=models.CheckConstraint(
            condition=models.Q(status__in=("draft", "sent", "acknowledged", "cancelled", "received",
                                           "short_closed", "closed")), name="ops_po_status_allowed")),
        migrations.AddConstraint(model_name="supplierpayment", constraint=models.UniqueConstraint(
            fields=("dataset_kind", "payment_ref"), name="ops_supplier_payment_ref")),
        migrations.AddConstraint(model_name="supplierpayment", constraint=models.CheckConstraint(
            condition=models.Q(payment_kind__in=("deposit", "balance", "deposit_refund", "deposit_forfeit")),
            name="ops_supplier_payment_kind")),
        migrations.AddConstraint(model_name="supplierpayment", constraint=models.CheckConstraint(
            condition=models.Q(amount_twd__gt=0), name="ops_supplier_payment_positive")),
        migrations.AddConstraint(model_name="supplierpayment", constraint=models.CheckConstraint(
            condition=models.Q(bank_account="1121"), name="ops_supplier_payment_bank_1121")),
        migrations.AddConstraint(model_name="supplierpayment", constraint=models.CheckConstraint(
            condition=~models.Q(evidence_ref=""), name="ops_supplier_payment_evidence")),
        migrations.AddConstraint(model_name="supplierpayment", constraint=models.CheckConstraint(
            condition=(models.Q(invoice__isnull=False, payment_kind="balance") |
                       (models.Q(invoice__isnull=True) & ~models.Q(payment_kind="balance"))),
            name="ops_supplier_payment_invoice_shape")),
        migrations.AddConstraint(model_name="supplierpayment", constraint=models.CheckConstraint(
            condition=models.Q(payment_kind="deposit_forfeit") | ~models.Q(bank_ref=""),
            name="ops_supplier_payment_bank_ref")),
        migrations.AddConstraint(model_name="supplierpayment", constraint=models.CheckConstraint(
            condition=~models.Q(payment_kind="deposit_forfeit") | models.Q(bank_ref=""),
            name="ops_supplier_forfeit_no_bank_ref")),
        migrations.RunSQL(PAYMENT_APPEND_ONLY_SQL, PAYMENT_APPEND_ONLY_REVERSE_SQL),
        migrations.RunSQL(PO_FORWARD_ONLY_SQL, G2.PO_FORWARD_ONLY_SQL),
        migrations.RunPython(migrations.RunPython.noop, refuse_reverse),
    ]
