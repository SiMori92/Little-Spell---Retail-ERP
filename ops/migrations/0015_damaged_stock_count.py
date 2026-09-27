from django.db import migrations, models


SELLABLE_VIEW_SQL = """
DROP VIEW IF EXISTS ops_on_hand;
CREATE VIEW ops_on_hand AS
SELECT move.product_id AS sku, SUM(move.qty_delta_pieces)::bigint AS qty_pieces
FROM ops_inventorymove AS move
WHERE NOT EXISTS (
    SELECT 1
    FROM ops_stockcountline AS damaged
    INNER JOIN ops_stockcount AS stock_count ON stock_count.id = damaged.count_id
    WHERE move.kind IN ('opening', 'adjusted')
      AND damaged.product_id = move.product_id
      AND damaged.dataset_kind = move.dataset_kind
      AND damaged.source_filename = move.source_filename
      AND stock_count.counted_at = (move.occurred_at AT TIME ZONE 'Asia/Taipei')::date
      AND damaged.condition = 'damaged_unsellable'
      AND NOT EXISTS (
          SELECT 1
          FROM ops_stockcountline AS sellable
          WHERE sellable.count_id = damaged.count_id
            AND sellable.product_id = damaged.product_id
            AND sellable.condition = 'sellable'
      )
)
GROUP BY move.product_id;
GRANT SELECT ON ops_on_hand TO ops_writer, acct_writer, reporter;
"""


OLD_VIEW_SQL = """
DROP VIEW IF EXISTS ops_on_hand;
CREATE VIEW ops_on_hand AS
SELECT product_id AS sku, SUM(qty_delta_pieces)::bigint AS qty_pieces
FROM ops_inventorymove
GROUP BY product_id;
GRANT SELECT ON ops_on_hand TO ops_writer, acct_writer, reporter;
"""


class Migration(migrations.Migration):

    dependencies = [("ops", "0014_supplier_payments")]

    operations = [
        migrations.RemoveConstraint(
            model_name="stockcountline",
            name="ops_count_one_line_per_sku",
        ),
        migrations.AddConstraint(
            model_name="stockcountline",
            constraint=models.UniqueConstraint(
                fields=("count", "product", "condition"),
                name="ops_count_one_line_per_sku_condition",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockcountline",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(condition="sellable") |
                    models.Q(condition="damaged_unsellable", qty_pieces__gt=0,
                             agreed_unit_cost_twd=0, line_value_twd=0)
                ),
                name="ops_count_damaged_positive_nil_value",
            ),
        ),
        migrations.RunSQL(SELLABLE_VIEW_SQL, OLD_VIEW_SQL),
    ]
