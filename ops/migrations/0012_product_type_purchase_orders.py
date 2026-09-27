# Generated for Slice G-1 on 2026-09-27.

import django.db.models.deletion
import django.db.models.expressions
from django.db import migrations, models


# G-1 I-6 in the database (the H-0a pattern): an append-only status history, a
# forward-only current state that must be explained by a history row, and frozen
# commercial fields once a PO leaves draft. The intake refuses the same things
# first, with named messages; these triggers hold even for a direct SQL writer.
STATUS_APPEND_ONLY_SQL = """
CREATE OR REPLACE FUNCTION ops_purchaseorderstatus_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ops_purchaseorderstatus is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER ops_purchaseorderstatus_append_only
    BEFORE UPDATE OR DELETE ON ops_purchaseorderstatus
    FOR EACH ROW EXECUTE FUNCTION ops_purchaseorderstatus_append_only();
"""

STATUS_APPEND_ONLY_REVERSE_SQL = """
DROP TRIGGER IF EXISTS ops_purchaseorderstatus_append_only ON ops_purchaseorderstatus;
DROP FUNCTION IF EXISTS ops_purchaseorderstatus_append_only();
"""

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
        IF NEW.po_number IS DISTINCT FROM OLD.po_number OR NEW.dataset_kind IS DISTINCT FROM OLD.dataset_kind THEN
            RAISE EXCEPTION 'ops_purchaseorder po_number and dataset_kind cannot change';
        END IF;
        IF NEW.status <> OLD.status AND NOT (
            (OLD.status = 'draft' AND NEW.status IN ('sent', 'cancelled')) OR
            (OLD.status = 'sent' AND NEW.status IN ('acknowledged', 'cancelled')) OR
            (OLD.status = 'acknowledged' AND NEW.status = 'cancelled')
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
CREATE TRIGGER ops_purchaseorder_forward_only
    BEFORE INSERT OR UPDATE OR DELETE ON ops_purchaseorder
    FOR EACH ROW EXECUTE FUNCTION ops_purchaseorder_forward_only();
"""

PO_FORWARD_ONLY_REVERSE_SQL = """
DROP TRIGGER IF EXISTS ops_purchaseorder_forward_only ON ops_purchaseorder;
DROP FUNCTION IF EXISTS ops_purchaseorder_forward_only();
"""

PO_LINE_FROZEN_SQL = """
CREATE OR REPLACE FUNCTION ops_purchaseorderline_frozen_once_sent() RETURNS trigger AS $$
DECLARE
    parent_status text;
    parent_number text;
BEGIN
    SELECT status, po_number INTO parent_status, parent_number FROM ops_purchaseorder
    WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.po_id ELSE NEW.po_id END;
    IF TG_OP = 'UPDATE' AND NEW.po_id IS DISTINCT FROM OLD.po_id THEN
        RAISE EXCEPTION 'ops_purchaseorderline cannot move to another purchase order';
    END IF;
    IF parent_status = 'draft' THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_OP IN ('INSERT', 'DELETE') THEN
        RAISE EXCEPTION 'ops_purchaseorderline % on % is not permitted once the PO is %', TG_OP, parent_number, parent_status;
    END IF;
    IF NEW.line_no IS DISTINCT FROM OLD.line_no OR
       NEW.product_id IS DISTINCT FROM OLD.product_id OR
       NEW.qty_pieces IS DISTINCT FROM OLD.qty_pieces OR
       NEW.unit_price_twd IS DISTINCT FROM OLD.unit_price_twd OR
       NEW.setup_charge_twd IS DISTINCT FROM OLD.setup_charge_twd OR
       NEW.line_total_twd IS DISTINCT FROM OLD.line_total_twd THEN
        RAISE EXCEPTION 'ops_purchaseorderline sku, qty_pieces, unit_price_twd and setup_charge_twd on % are frozen once %', parent_number, parent_status;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER ops_purchaseorderline_frozen_once_sent
    BEFORE INSERT OR UPDATE OR DELETE ON ops_purchaseorderline
    FOR EACH ROW EXECUTE FUNCTION ops_purchaseorderline_frozen_once_sent();
"""

PO_LINE_FROZEN_REVERSE_SQL = """
DROP TRIGGER IF EXISTS ops_purchaseorderline_frozen_once_sent ON ops_purchaseorderline;
DROP FUNCTION IF EXISTS ops_purchaseorderline_frozen_once_sent();
"""


def refuse_reverse_with_packaging(apps, schema_editor):
    # The pre-G-1 CHECK cannot hold NOT_APPLICABLE; say so instead of a raw CHECK error.
    Product = apps.get_model("ops", "Product")
    packaging = sorted(Product.objects.filter(product_type="packaging").values_list("sku", flat=True))
    if packaging:
        raise RuntimeError("Reversing G-1 refused: packaging products exist ("
                           + ", ".join(packaging) + "); the pre-G-1 schema cannot represent them.")


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0011_piece_inventory_unit'),
    ]

    operations = [
        migrations.CreateModel(
            name='PurchaseOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_filename', models.CharField(max_length=255)),
                ('dataset_kind', models.CharField(choices=[('SAMPLE', 'Sample data — not actuals'), ('ACTUAL', 'Actual data')], max_length=6)),
                ('po_number', models.CharField(max_length=11)),
                ('po_date', models.DateField()),
                ('target_delivery_date', models.DateField()),
                ('currency', models.CharField(max_length=3)),
                ('payment_terms', models.CharField(max_length=255)),
                ('incoterm', models.CharField(choices=[('EXW', 'EXW'), ('FCA', 'FCA'), ('CPT', 'CPT'), ('CIP', 'CIP'), ('DAP', 'DAP'), ('DPU', 'DPU'), ('DDP', 'DDP'), ('FAS', 'FAS'), ('FOB', 'FOB'), ('CFR', 'CFR'), ('CIF', 'CIF')], max_length=3)),
                ('quote_ref', models.CharField(max_length=255)),
                ('status', models.CharField(choices=[('draft', 'draft'), ('sent', 'sent'), ('acknowledged', 'acknowledged'), ('cancelled', 'cancelled')], max_length=12)),
            ],
        ),
        migrations.CreateModel(
            name='PurchaseOrderLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_filename', models.CharField(max_length=255)),
                ('dataset_kind', models.CharField(choices=[('SAMPLE', 'Sample data — not actuals'), ('ACTUAL', 'Actual data')], max_length=6)),
                ('line_no', models.PositiveIntegerField()),
                ('qty_pieces', models.PositiveIntegerField()),
                ('unit_price_twd', models.DecimalField(decimal_places=4, max_digits=18)),
                ('setup_charge_twd', models.DecimalField(decimal_places=4, max_digits=18)),
                ('line_total_twd', models.DecimalField(decimal_places=4, max_digits=18)),
                ('min_order_qty_pieces', models.PositiveIntegerField(blank=True, null=True)),
                ('artwork_ref', models.CharField(blank=True, default='', max_length=255)),
                ('evidence_ref', models.CharField(max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name='PurchaseOrderStatus',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_filename', models.CharField(max_length=255)),
                ('dataset_kind', models.CharField(choices=[('SAMPLE', 'Sample data — not actuals'), ('ACTUAL', 'Actual data')], max_length=6)),
                ('po_number', models.CharField(max_length=11)),
                ('status', models.CharField(choices=[('draft', 'draft'), ('sent', 'sent'), ('acknowledged', 'acknowledged'), ('cancelled', 'cancelled')], max_length=12)),
                ('effective_on', models.DateField()),
            ],
        ),
        migrations.RemoveConstraint(
            model_name='product',
            name='ops_product_ingredient_ref_shape',
        ),
        migrations.AddField(
            model_name='product',
            name='product_type',
            field=models.CharField(choices=[('sellable', 'sellable'), ('packaging', 'packaging')], default='sellable', max_length=9),
        ),
        migrations.AddConstraint(
            model_name='product',
            constraint=models.CheckConstraint(condition=models.Q(('product_type__in', ('sellable', 'packaging'))), name='ops_product_type_allowed'),
        ),
        migrations.AddConstraint(
            model_name='product',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('product_type', 'sellable'), models.Q(('ingredient_ref', 'UNKNOWN'), models.Q(('ingredient_ref__startswith', 'compliance/suppliers/'), models.Q(('ingredient_ref', 'compliance/suppliers/'), _negated=True)), _connector='OR')), models.Q(('ingredient_ref', 'NOT_APPLICABLE'), ('product_type', 'packaging')), _connector='OR'), name='ops_product_ingredient_ref_shape'),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='supplier',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='ops.supplier'),
        ),
        migrations.AddField(
            model_name='purchaseorderline',
            name='po',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lines', to='ops.purchaseorder'),
        ),
        migrations.AddField(
            model_name='purchaseorderline',
            name='product',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='ops.product'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorderstatus',
            constraint=models.UniqueConstraint(fields=('dataset_kind', 'po_number', 'status'), name='ops_po_status_once'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorder',
            constraint=models.UniqueConstraint(fields=('dataset_kind', 'po_number'), name='ops_po_dataset_number'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorder',
            constraint=models.CheckConstraint(condition=models.Q(('po_number__regex', '^PO-[0-9]{4}-[0-9]{3}$')), name='ops_po_number_shape'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorder',
            constraint=models.CheckConstraint(condition=models.Q(('status__in', ('draft', 'sent', 'acknowledged', 'cancelled'))), name='ops_po_status_allowed'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorder',
            constraint=models.CheckConstraint(condition=models.Q(('incoterm__in', ('EXW', 'FCA', 'CPT', 'CIP', 'DAP', 'DPU', 'DDP', 'FAS', 'FOB', 'CFR', 'CIF'))), name='ops_po_incoterm_allowed'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorder',
            constraint=models.CheckConstraint(condition=models.Q(('currency', 'TWD')), name='ops_po_currency_twd'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorder',
            constraint=models.CheckConstraint(condition=models.Q(('quote_ref', ''), _negated=True), name='ops_po_quote_ref_required'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorder',
            constraint=models.CheckConstraint(condition=models.Q(('payment_terms', ''), _negated=True), name='ops_po_payment_terms_required'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorder',
            constraint=models.CheckConstraint(condition=models.Q(('target_delivery_date__gte', models.F('po_date'))), name='ops_po_target_after_po_date'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorderline',
            constraint=models.UniqueConstraint(fields=('po', 'line_no'), name='ops_po_line_once'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorderline',
            constraint=models.CheckConstraint(condition=models.Q(('line_no__gte', 1)), name='ops_po_line_positive'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorderline',
            constraint=models.CheckConstraint(condition=models.Q(('qty_pieces__gt', 0)), name='ops_po_line_positive_pieces'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorderline',
            constraint=models.CheckConstraint(condition=models.Q(('unit_price_twd__gt', 0)), name='ops_po_line_positive_price'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorderline',
            constraint=models.CheckConstraint(condition=models.Q(('setup_charge_twd__gte', 0)), name='ops_po_line_setup_nonnegative'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorderline',
            constraint=models.CheckConstraint(condition=models.Q(('line_total_twd', django.db.models.expressions.CombinedExpression(django.db.models.expressions.CombinedExpression(models.F('qty_pieces'), '*', models.F('unit_price_twd')), '+', models.F('setup_charge_twd')))), name='ops_po_line_total_identity'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorderline',
            constraint=models.CheckConstraint(condition=models.Q(('min_order_qty_pieces__isnull', True), ('qty_pieces__gte', models.F('min_order_qty_pieces')), _connector='OR'), name='ops_po_line_meets_moq'),
        ),
        migrations.AddConstraint(
            model_name='purchaseorderline',
            constraint=models.CheckConstraint(condition=models.Q(('evidence_ref', ''), _negated=True), name='ops_po_line_evidence_required'),
        ),
        migrations.RunSQL(STATUS_APPEND_ONLY_SQL, STATUS_APPEND_ONLY_REVERSE_SQL),
        migrations.RunSQL(PO_FORWARD_ONLY_SQL, PO_FORWARD_ONLY_REVERSE_SQL),
        migrations.RunSQL(PO_LINE_FROZEN_SQL, PO_LINE_FROZEN_REVERSE_SQL),
        # Last forward, therefore first in reverse.
        migrations.RunPython(migrations.RunPython.noop, refuse_reverse_with_packaging),
    ]
