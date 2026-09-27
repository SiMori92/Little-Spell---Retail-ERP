# Generated for Slice G-0.1 on 2026-09-27.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("ops", "0007_supplier_product_compliance")]

    operations = [
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(
                condition=(models.Q(("ingredient_ref", "UNKNOWN")) |
                           (models.Q(("ingredient_ref__startswith", "compliance/suppliers/")) &
                            ~models.Q(("ingredient_ref", "compliance/suppliers/")))),
                name="ops_product_ingredient_ref_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplier",
            constraint=models.CheckConstraint(
                condition=(models.Q(("declaration_ref", "")) |
                           (models.Q(("declaration_ref__startswith", "compliance/suppliers/")) &
                            ~models.Q(("declaration_ref", "compliance/suppliers/")))),
                name="ops_supplier_declaration_ref_shape",
            ),
        ),
    ]
