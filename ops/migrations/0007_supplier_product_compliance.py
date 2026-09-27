# Generated for Slice G-0 on 2026-09-27.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("ops", "0006_receipt_stockcount_stockcountline")]

    operations = [
        migrations.CreateModel(
            name="Supplier",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_filename", models.CharField(max_length=255)),
                ("dataset_kind", models.CharField(choices=[("SAMPLE", "Sample data — not actuals"), ("ACTUAL", "Actual data")], max_length=6)),
                ("supplier_ref", models.CharField(max_length=7)),
                ("legal_name", models.CharField(max_length=255)),
                ("country", models.CharField(max_length=2)),
                ("currency", models.CharField(max_length=3)),
                ("default_incoterm", models.CharField(max_length=3)),
                ("payment_terms", models.CharField(max_length=255)),
                ("can_invoice_to_tax_id", models.CharField(max_length=7)),
                ("declaration_ref", models.CharField(blank=True, default="", max_length=255)),
                ("evidence_ref", models.CharField(max_length=255)),
            ],
        ),
        migrations.AddField(
            model_name="product", name="ingredient_ref",
            field=models.CharField(default="UNKNOWN", max_length=255),
        ),
        migrations.AddField(
            model_name="product", name="supplier",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    to="ops.supplier"),
        ),
        migrations.CreateModel(
            name="SupplierChange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_filename", models.CharField(max_length=255)),
                ("dataset_kind", models.CharField(choices=[("SAMPLE", "Sample data — not actuals"), ("ACTUAL", "Actual data")], max_length=6)),
                ("supplier_ref", models.CharField(max_length=7)),
                ("field", models.CharField(max_length=32)),
                ("old", models.TextField(blank=True, default="")),
                ("new", models.TextField(blank=True, default="")),
                ("evidence_ref", models.CharField(max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name="ProductComplianceChange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_filename", models.CharField(max_length=255)),
                ("dataset_kind", models.CharField(choices=[("SAMPLE", "Sample data — not actuals"), ("ACTUAL", "Actual data")], max_length=6)),
                ("sku", models.CharField(max_length=20)),
                ("field", models.CharField(max_length=32)),
                ("old", models.TextField(blank=True, default="")),
                ("new", models.TextField(blank=True, default="")),
                ("evidence_ref", models.CharField(max_length=255)),
            ],
        ),
        migrations.AddConstraint(
            model_name="supplier",
            constraint=models.UniqueConstraint(fields=("dataset_kind", "supplier_ref"),
                                               name="ops_supplier_dataset_ref"),
        ),
    ]
