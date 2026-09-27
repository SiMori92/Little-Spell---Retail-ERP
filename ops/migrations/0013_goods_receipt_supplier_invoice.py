# Generated for Slice G-2 on 2026-09-27.

import django.db.models.deletion
import django.db.models.expressions
from django.db import migrations, models

import importlib

G1 = importlib.import_module("ops.migrations.0012_product_type_purchase_orders")

# G-2 in the database, the G-1 pattern. The intake refuses first with named
# messages; these hold even for a direct SQL writer.
APPEND_ONLY_TABLES = ("ops_goodsreceipt", "ops_goodsreceiptline", "ops_supplierinvoice", "ops_supplierinvoiceline")

APPEND_ONLY_SQL = """
CREATE OR REPLACE FUNCTION ops_purchase_document_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not permitted', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;
""" + "".join(f"""
CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}
    FOR EACH ROW EXECUTE FUNCTION ops_purchase_document_append_only();
""" for table in APPEND_ONLY_TABLES)

APPEND_ONLY_REVERSE_SQL = "".join(
    f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};\n" for table in APPEND_ONLY_TABLES
) + "DROP FUNCTION IF EXISTS ops_purchase_document_append_only();"

# A receipt or invoice line belongs to a line of ITS OWN PO and carries that line's SKU.
LINE_BELONGS_SQL = """
CREATE OR REPLACE FUNCTION ops_purchase_document_line_belongs() RETURNS trigger AS $$
DECLARE
    document_po bigint;
    line_po bigint;
    line_product text;
    line_number integer;
BEGIN
    IF TG_TABLE_NAME = 'ops_goodsreceiptline' THEN
        SELECT po_id INTO document_po FROM ops_goodsreceipt WHERE id = NEW.receipt_id;
    ELSE
        SELECT po_id INTO document_po FROM ops_supplierinvoice WHERE id = NEW.invoice_id;
    END IF;
    SELECT po_id, product_id, line_no INTO line_po, line_product, line_number
    FROM ops_purchaseorderline WHERE id = NEW.po_line_id;
    IF line_po IS DISTINCT FROM document_po OR line_number IS DISTINCT FROM NEW.line_no
       OR line_product IS DISTINCT FROM NEW.product_id THEN
        RAISE EXCEPTION '% line % must be a line of its own PO with the PO line SKU', TG_TABLE_NAME, NEW.line_no;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER ops_goodsreceiptline_belongs BEFORE INSERT ON ops_goodsreceiptline
    FOR EACH ROW EXECUTE FUNCTION ops_purchase_document_line_belongs();
CREATE TRIGGER ops_supplierinvoiceline_belongs BEFORE INSERT ON ops_supplierinvoiceline
    FOR EACH ROW EXECUTE FUNCTION ops_purchase_document_line_belongs();
"""

LINE_BELONGS_REVERSE_SQL = """
DROP TRIGGER IF EXISTS ops_goodsreceiptline_belongs ON ops_goodsreceiptline;
DROP TRIGGER IF EXISTS ops_supplierinvoiceline_belongs ON ops_supplierinvoiceline;
DROP FUNCTION IF EXISTS ops_purchase_document_line_belongs();
"""

# G-1's forward-only rule, extended: sent|acknowledged -> received|short_closed, reached
# only when every line has its receipt line; both are terminal; goods on hand block cancel.
PO_FORWARD_ONLY_SQL = """
CREATE OR REPLACE FUNCTION ops_purchaseorder_forward_only() RETURNS trigger AS $$
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
        IF OLD.status = 'cancelled' THEN
            RAISE EXCEPTION 'ops_purchaseorder % is cancelled; nothing leaves cancelled', OLD.po_number;
        END IF;
        IF OLD.status IN ('received', 'short_closed') THEN
            RAISE EXCEPTION 'ops_purchaseorder % is %; nothing leaves %', OLD.po_number, OLD.status, OLD.status;
        END IF;
        IF NEW.po_number IS DISTINCT FROM OLD.po_number OR NEW.dataset_kind IS DISTINCT FROM OLD.dataset_kind THEN
            RAISE EXCEPTION 'ops_purchaseorder po_number and dataset_kind cannot change';
        END IF;
        IF NEW.status <> OLD.status AND NOT (
            (OLD.status = 'draft' AND NEW.status IN ('sent', 'cancelled')) OR
            (OLD.status = 'sent' AND NEW.status IN ('acknowledged', 'cancelled', 'received', 'short_closed')) OR
            (OLD.status = 'acknowledged' AND NEW.status IN ('cancelled', 'received', 'short_closed'))
        ) THEN
            RAISE EXCEPTION 'ops_purchaseorder % status cannot move from % to %', OLD.po_number, OLD.status, NEW.status;
        END IF;
        IF OLD.status IN ('sent', 'acknowledged') AND (
            NEW.supplier_id IS DISTINCT FROM OLD.supplier_id OR
            NEW.currency IS DISTINCT FROM OLD.currency OR
            NEW.quote_ref IS DISTINCT FROM OLD.quote_ref
        ) THEN
            RAISE EXCEPTION 'ops_purchaseorder % supplier, currency and quote_ref are frozen once sent', OLD.po_number;
        END IF;
        IF NEW.status = 'cancelled' AND EXISTS (SELECT 1 FROM ops_goodsreceipt WHERE po_id = NEW.id) THEN
            RAISE EXCEPTION 'ops_purchaseorder % has goods received and cannot be cancelled', NEW.po_number;
        END IF;
        IF NEW.status IN ('received', 'short_closed') THEN
            IF EXISTS (
                SELECT 1 FROM ops_purchaseorderline l
                LEFT JOIN ops_goodsreceiptline r ON r.po_line_id = l.id
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


def refuse_reverse_with_receipts(apps, schema_editor):
    PurchaseOrder = apps.get_model("ops", "PurchaseOrder")
    reached = sorted(PurchaseOrder.objects.filter(status__in=["received", "short_closed"])
                     .values_list("po_number", flat=True))
    if reached:
        raise RuntimeError("Reversing G-2 refused: POs have been received (" + ", ".join(reached)
                           + "); the pre-G-2 schema cannot represent them.")



class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0012_product_type_purchase_orders'),
    ]

    operations = [
        migrations.CreateModel(
            name='GoodsReceipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_filename', models.CharField(max_length=255)),
                ('dataset_kind', models.CharField(choices=[('SAMPLE', 'Sample data — not actuals'), ('ACTUAL', 'Actual data')], max_length=6)),
                ('receipt_no', models.CharField(max_length=32)),
                ('received_on', models.DateField()),
            ],
        ),
        migrations.CreateModel(
            name='GoodsReceiptLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_filename', models.CharField(max_length=255)),
                ('dataset_kind', models.CharField(choices=[('SAMPLE', 'Sample data — not actuals'), ('ACTUAL', 'Actual data')], max_length=6)),
                ('line_no', models.PositiveIntegerField()),
                ('qty_pieces_good', models.PositiveIntegerField()),
                ('qty_pieces_damaged', models.PositiveIntegerField()),
                ('damaged_credited', models.BooleanField()),
                ('short_close', models.BooleanField()),
                ('short_close_reason', models.CharField(blank=True, default='', max_length=255)),
                ('evidence_ref', models.CharField(max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name='SupplierInvoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_filename', models.CharField(max_length=255)),
                ('dataset_kind', models.CharField(choices=[('SAMPLE', 'Sample data — not actuals'), ('ACTUAL', 'Actual data')], max_length=6)),
                ('invoice_no', models.CharField(max_length=32)),
                ('gui_no', models.CharField(blank=True, default='', max_length=10)),
                ('invoice_date', models.DateField()),
                ('receipt_no', models.CharField(max_length=32)),
                ('freight_twd', models.DecimalField(decimal_places=4, max_digits=18)),
                ('tax_twd', models.DecimalField(decimal_places=4, max_digits=18)),
                ('tax_creditable_twd', models.DecimalField(decimal_places=4, max_digits=18)),
                ('invoice_total_twd', models.DecimalField(decimal_places=4, max_digits=18)),
                ('deposit_applied_twd', models.DecimalField(decimal_places=4, max_digits=18)),
                ('evidence_ref', models.CharField(max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name='SupplierInvoiceLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_filename', models.CharField(max_length=255)),
                ('dataset_kind', models.CharField(choices=[('SAMPLE', 'Sample data — not actuals'), ('ACTUAL', 'Actual data')], max_length=6)),
                ('line_no', models.PositiveIntegerField()),
                ('qty_pieces_invoiced', models.PositiveIntegerField()),
                ('unit_price_twd', models.DecimalField(decimal_places=4, max_digits=18)),
                ('setup_charge_twd', models.DecimalField(decimal_places=4, max_digits=18)),
                ('line_amount_twd', models.DecimalField(decimal_places=4, max_digits=18)),
            ],
        ),
        migrations.RemoveConstraint(
            model_name='purchaseorder',
            name='ops_po_status_allowed',
        ),
        migrations.AlterField(
            model_name='purchaseorder',
            name='status',
            field=models.CharField(choices=[('draft', 'draft'), ('sent', 'sent'), ('acknowledged', 'acknowledged'), ('cancelled', 'cancelled'), ('received', 'received'), ('short_closed', 'short_closed')], max_length=12),
        ),
        migrations.AlterField(
            model_name='purchaseorderstatus',
            name='status',
            field=models.CharField(choices=[('draft', 'draft'), ('sent', 'sent'), ('acknowledged', 'acknowledged'), ('cancelled', 'cancelled'), ('received', 'received'), ('short_closed', 'short_closed')], max_length=12),
        ),
        migrations.AddConstraint(
            model_name='purchaseorder',
            constraint=models.CheckConstraint(condition=models.Q(('status__in', ('draft', 'sent', 'acknowledged', 'cancelled', 'received', 'short_closed'))), name='ops_po_status_allowed'),
        ),
        migrations.AddField(
            model_name='goodsreceipt',
            name='po',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='receipts', to='ops.purchaseorder'),
        ),
        migrations.AddField(
            model_name='goodsreceiptline',
            name='po_line',
            field=models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='receipt_line', to='ops.purchaseorderline'),
        ),
        migrations.AddField(
            model_name='goodsreceiptline',
            name='product',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='ops.product'),
        ),
        migrations.AddField(
            model_name='goodsreceiptline',
            name='receipt',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lines', to='ops.goodsreceipt'),
        ),
        migrations.AddField(
            model_name='supplierinvoice',
            name='po',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='invoices', to='ops.purchaseorder'),
        ),
        migrations.AddField(
            model_name='supplierinvoiceline',
            name='invoice',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lines', to='ops.supplierinvoice'),
        ),
        migrations.AddField(
            model_name='supplierinvoiceline',
            name='po_line',
            field=models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='invoice_line', to='ops.purchaseorderline'),
        ),
        migrations.AddField(
            model_name='supplierinvoiceline',
            name='product',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='ops.product'),
        ),
        migrations.AddConstraint(
            model_name='goodsreceipt',
            constraint=models.UniqueConstraint(fields=('po', 'receipt_no'), name='ops_grn_once_per_po'),
        ),
        migrations.AddConstraint(
            model_name='goodsreceipt',
            constraint=models.CheckConstraint(condition=models.Q(('receipt_no__regex', '^[A-Z0-9][A-Z0-9-]{0,31}$')), name='ops_grn_receipt_no_shape'),
        ),
        migrations.AddConstraint(
            model_name='goodsreceiptline',
            constraint=models.UniqueConstraint(fields=('receipt', 'line_no'), name='ops_grn_line_once'),
        ),
        migrations.AddConstraint(
            model_name='goodsreceiptline',
            constraint=models.CheckConstraint(condition=models.Q(('qty_pieces_good__gt', 0), models.Q(('qty_pieces_damaged__gt', 0), ('damaged_credited', False)), _connector='OR'), name='ops_grn_line_accepts_pieces'),
        ),
        migrations.AddConstraint(
            model_name='goodsreceiptline',
            constraint=models.CheckConstraint(condition=models.Q(('qty_pieces_damaged__gt', 0), ('damaged_credited', False), _connector='OR'), name='ops_grn_credit_needs_damage'),
        ),
        migrations.AddConstraint(
            model_name='goodsreceiptline',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('short_close', True), models.Q(('short_close_reason', ''), _negated=True)), models.Q(('short_close', False), ('short_close_reason', '')), _connector='OR'), name='ops_grn_short_close_reason'),
        ),
        migrations.AddConstraint(
            model_name='goodsreceiptline',
            constraint=models.CheckConstraint(condition=models.Q(('evidence_ref', ''), _negated=True), name='ops_grn_line_evidence_required'),
        ),
        migrations.AddConstraint(
            model_name='supplierinvoice',
            constraint=models.UniqueConstraint(fields=('dataset_kind', 'invoice_no'), name='ops_invoice_dataset_number'),
        ),
        migrations.AddConstraint(
            model_name='supplierinvoice',
            constraint=models.UniqueConstraint(fields=('po', 'receipt_no'), name='ops_invoice_once_per_receipt'),
        ),
        migrations.AddConstraint(
            model_name='supplierinvoice',
            constraint=models.CheckConstraint(condition=models.Q(('freight_twd__gte', 0)), name='ops_invoice_freight_nonnegative'),
        ),
        migrations.AddConstraint(
            model_name='supplierinvoice',
            constraint=models.CheckConstraint(condition=models.Q(('tax_creditable_twd__gte', 0), ('tax_creditable_twd__lte', models.F('tax_twd'))), name='ops_invoice_creditable_within_tax'),
        ),
        migrations.AddConstraint(
            model_name='supplierinvoice',
            constraint=models.CheckConstraint(condition=models.Q(('tax_creditable_twd', 0), models.Q(('gui_no', ''), _negated=True), _connector='OR'), name='ops_invoice_creditable_needs_gui'),
        ),
        migrations.AddConstraint(
            model_name='supplierinvoice',
            constraint=models.CheckConstraint(condition=models.Q(('deposit_applied_twd', 0)), name='ops_invoice_no_deposit_before_g3'),
        ),
        migrations.AddConstraint(
            model_name='supplierinvoice',
            constraint=models.CheckConstraint(condition=models.Q(('gui_no', ''), ('gui_no__regex', '^[A-Z]{2}[0-9]{8}$'), _connector='OR'), name='ops_invoice_gui_no_shape'),
        ),
        migrations.AddConstraint(
            model_name='supplierinvoice',
            constraint=models.CheckConstraint(condition=models.Q(('evidence_ref', ''), _negated=True), name='ops_invoice_evidence_required'),
        ),
        migrations.AddConstraint(
            model_name='supplierinvoiceline',
            constraint=models.UniqueConstraint(fields=('invoice', 'line_no'), name='ops_invoice_line_once'),
        ),
        migrations.AddConstraint(
            model_name='supplierinvoiceline',
            constraint=models.CheckConstraint(condition=models.Q(('qty_pieces_invoiced__gt', 0)), name='ops_invoice_line_positive_pieces'),
        ),
        migrations.AddConstraint(
            model_name='supplierinvoiceline',
            constraint=models.CheckConstraint(condition=models.Q(('line_amount_twd', django.db.models.expressions.CombinedExpression(django.db.models.expressions.CombinedExpression(models.F('qty_pieces_invoiced'), '*', models.F('unit_price_twd')), '+', models.F('setup_charge_twd')))), name='ops_invoice_line_amount_identity'),
        ),
        migrations.RunSQL(APPEND_ONLY_SQL, APPEND_ONLY_REVERSE_SQL),
        migrations.RunSQL(LINE_BELONGS_SQL, LINE_BELONGS_REVERSE_SQL),
        # Reverse restores G-1's function body exactly.
        migrations.RunSQL(PO_FORWARD_ONLY_SQL, G1.PO_FORWARD_ONLY_SQL.split("CREATE TRIGGER")[0]),
        # Last forward, therefore first in reverse.
        migrations.RunPython(migrations.RunPython.noop, refuse_reverse_with_receipts),
    ]
