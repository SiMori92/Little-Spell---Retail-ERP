# Generated for Slice H-0a on 2026-09-27.

import django.db.models.deletion
from django.db import migrations, models


STATUS_APPEND_ONLY_SQL = """
CREATE OR REPLACE FUNCTION ops_igdealstatus_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ops_igdealstatus is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER ops_igdealstatus_append_only
    BEFORE UPDATE OR DELETE ON ops_igdealstatus
    FOR EACH ROW EXECUTE FUNCTION ops_igdealstatus_append_only();
"""

STATUS_APPEND_ONLY_REVERSE_SQL = """
DROP TRIGGER IF EXISTS ops_igdealstatus_append_only ON ops_igdealstatus;
DROP FUNCTION IF EXISTS ops_igdealstatus_append_only();
"""


class Migration(migrations.Migration):

    dependencies = [("ops", "0008_product_supplier_compliance_ref_shape")]

    operations = [
        migrations.CreateModel(
            name="IgDealStatus",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_filename", models.CharField(max_length=255)),
                ("dataset_kind", models.CharField(choices=[("SAMPLE", "Sample data — not actuals"), ("ACTUAL", "Actual data")], max_length=6)),
                ("deal_id", models.CharField(max_length=13)),
                ("status", models.CharField(choices=[("enquiry", "enquiry"), ("quoted", "quoted"), ("paid", "paid"), ("shipped", "shipped"), ("followed_up", "followed_up"), ("lost", "lost")], max_length=16)),
                ("effective_on", models.DateField()),
            ],
            options={"constraints": [models.UniqueConstraint(
                fields=("dataset_kind", "deal_id", "status"), name="ops_ig_status_once")]},
        ),
        migrations.CreateModel(
            name="IgDeal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_filename", models.CharField(max_length=255)),
                ("dataset_kind", models.CharField(choices=[("SAMPLE", "Sample data — not actuals"), ("ACTUAL", "Actual data")], max_length=6)),
                ("deal_id", models.CharField(max_length=13)),
                ("line_no", models.PositiveIntegerField()),
                ("customer_ref", models.CharField(max_length=32)),
                ("status", models.CharField(choices=[("enquiry", "enquiry"), ("quoted", "quoted"), ("paid", "paid"), ("shipped", "shipped"), ("followed_up", "followed_up"), ("lost", "lost")], max_length=16)),
                ("enquiry_at", models.DateField()),
                ("quoted_at", models.DateField(blank=True, null=True)),
                ("quote_twd", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("follow_up_on", models.DateField(blank=True, null=True)),
                ("lost_reason", models.CharField(blank=True, default="", max_length=24)),
                ("qty_packs", models.PositiveIntegerField(blank=True, null=True)),
                ("unit_price_twd", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("shipping_charged_twd", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("ship_country", models.CharField(blank=True, default="", max_length=2)),
                ("paid_at", models.DateField(blank=True, null=True)),
                ("wallet_txn_id", models.CharField(blank=True, default="", max_length=100)),
                ("ship_date", models.DateField(blank=True, null=True)),
                ("consent_marketing", models.CharField(blank=True, default="", max_length=3)),
                ("journey_sent", models.CharField(default="none", max_length=4)),
                ("evidence_ref", models.CharField(max_length=255)),
                ("product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="ops.product")),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("dataset_kind", "deal_id", "line_no"), name="ops_ig_deal_dataset_line"),
                models.CheckConstraint(condition=models.Q(("line_no__gte", 1)), name="ops_ig_deal_line_positive"),
                models.CheckConstraint(condition=models.Q(("quote_twd__isnull", True), ("quote_twd__gt", 0), _connector="OR"), name="ops_ig_deal_quote_positive"),
                models.CheckConstraint(condition=models.Q(("qty_packs__isnull", True), ("qty_packs__gt", 0), _connector="OR"), name="ops_ig_deal_qty_positive"),
                models.CheckConstraint(condition=models.Q(("unit_price_twd__isnull", True), ("unit_price_twd__gt", 0), _connector="OR"), name="ops_ig_deal_price_positive"),
                models.CheckConstraint(condition=models.Q(("shipping_charged_twd__isnull", True), ("shipping_charged_twd__gte", 0), _connector="OR"), name="ops_ig_deal_shipping_nonnegative"),
                models.CheckConstraint(condition=models.Q(("consent_marketing__in", ["", "yes", "no"])), name="ops_ig_deal_consent_allowed"),
                models.CheckConstraint(condition=models.Q(("journey_sent__in", ["none", "d0", "d10", "d30"])), name="ops_ig_deal_journey_allowed"),
            ]},
        ),
        migrations.RunSQL(STATUS_APPEND_ONLY_SQL, STATUS_APPEND_ONLY_REVERSE_SQL),
    ]
