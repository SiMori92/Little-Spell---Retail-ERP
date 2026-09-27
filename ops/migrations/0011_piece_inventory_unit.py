"""Slice U: make the piece the inventory unit without rewriting recorded quantities."""

from django.db import migrations, models
from django.db.models import Q


REFUSAL = (
    "Unit migration refused: SAMPLE data holds pack quantities for {skus}. "
    "Reset the SAMPLE database and re-import the samples (catalogue Addendum F.4)."
)


def refuse_unsafe_data(apps, schema_editor):
    # ACTUAL is immutable for this migration. The singleton is included because a
    # database already flipped to ACTUAL must refuse even if its business tables
    # happen to be empty.
    settings = apps.get_model("core", "DatasetSettings")
    if settings.objects.filter(dataset_kind="ACTUAL").exists():
        raise RuntimeError("Unit migration refused: ACTUAL dataset rows exist.")
    for model in apps.get_models():
        if any(field.name == "dataset_kind" for field in model._meta.fields):
            if model.objects.filter(dataset_kind="ACTUAL").exists():
                raise RuntimeError("Unit migration refused: ACTUAL dataset rows exist.")

    Product = apps.get_model("ops", "Product")
    invalid = list(Product.objects.filter(pack_qty__isnull=True).values_list("sku", flat=True))
    if invalid:
        raise RuntimeError(
            "Unit migration refused: products lack a positive conversion factor for "
            + ", ".join(sorted(invalid))
        )
    affected = set(Product.objects.exclude(pack_qty=1).values_list("sku", flat=True))
    if not affected:
        return

    held = set()
    relations = (
        ("ops", "InventoryMove", "product_id"),
        ("ops", "StockCountLine", "product_id"),
        ("ops", "OrderLine", "product_id"),
        ("ops", "IgDeal", "product_id"),
        ("acct", "WacPosition", "sku"),
    )
    for app_label, model_name, field in relations:
        model = apps.get_model(app_label, model_name)
        held.update(model.objects.filter(**{f"{field}__in": affected}).values_list(field, flat=True))

    JournalLine = apps.get_model("acct", "JournalLine")
    held.update(JournalLine.objects.filter(
        sku__in=affected, qty_delta_packs__isnull=False
    ).values_list("sku", flat=True))

    LedgerEvent = apps.get_model("ops", "LedgerEvent")
    for payload in LedgerEvent.objects.values_list("payload", flat=True):
        stack = [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if item.get("sku") in affected and any(
                    key in item for key in ("qty_packs", "qty")
                ):
                    held.add(item["sku"])
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)

    if held:
        raise RuntimeError(REFUSAL.format(skus=", ".join(sorted(held))))


def rewrite_product_uom(apps, schema_editor):
    """Run only after the old PK check has been removed."""
    Product = apps.get_model("ops", "Product")
    Product.objects.update(uom="PC")


IG_TRIGGER_V2 = """
CREATE OR REPLACE FUNCTION ops_igdeal_forward_only() RETURNS trigger AS $$
DECLARE
    old_rank integer;
    new_rank integer;
BEGIN
    old_rank := CASE OLD.status WHEN 'enquiry' THEN 0 WHEN 'quoted' THEN 1 WHEN 'paid' THEN 2
        WHEN 'shipped' THEN 3 WHEN 'followed_up' THEN 4 WHEN 'lost' THEN 5 END;
    new_rank := CASE NEW.status WHEN 'enquiry' THEN 0 WHEN 'quoted' THEN 1 WHEN 'paid' THEN 2
        WHEN 'shipped' THEN 3 WHEN 'followed_up' THEN 4 WHEN 'lost' THEN 5 END;
    IF NEW.status = OLD.status THEN
        RAISE EXCEPTION 'ops_igdeal current state can change only with a forward status move';
    END IF;
    IF OLD.status = 'lost' OR (NEW.status <> 'lost' AND new_rank < old_rank) THEN
        RAISE EXCEPTION 'ops_igdeal status cannot move backward from % to %', OLD.status, NEW.status;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM ops_igdealstatus
        WHERE dataset_kind = NEW.dataset_kind AND deal_id = NEW.deal_id AND status = NEW.status
    ) THEN
        RAISE EXCEPTION 'ops_igdeal forward move requires its IgDealStatus history row';
    END IF;
    IF NEW.status IN ('paid', 'shipped', 'followed_up')
       AND OLD.quote_twd IS NOT NULL AND OLD.quote_twd IS DISTINCT FROM NEW.quote_twd THEN
        RAISE EXCEPTION 'ops_igdeal quote_twd cannot change once status >= paid';
    END IF;
    IF OLD.status IN ('paid', 'shipped', 'followed_up') AND (
        OLD.product_id IS DISTINCT FROM NEW.product_id OR
        OLD.qty_sale_units IS DISTINCT FROM NEW.qty_sale_units OR
        OLD.unit_price_twd IS DISTINCT FROM NEW.unit_price_twd OR
        OLD.wallet_txn_id IS DISTINCT FROM NEW.wallet_txn_id
    ) THEN
        RAISE EXCEPTION 'ops_igdeal paid fields cannot change once status >= paid';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

IG_TRIGGER_V1 = IG_TRIGGER_V2.replace("qty_sale_units", "qty_packs")


class Migration(migrations.Migration):
    dependencies = [
        ("ops", "0010_igdeal_date_order"),
        ("acct", "0006_remove_journalline_acct_line_one_side_and_more"),
        ("core", "0002_database_roles"),
    ]

    operations = [
        migrations.RunPython(refuse_unsafe_data, migrations.RunPython.noop),
        migrations.RemoveConstraint("product", "ops_product_pack_uom"),
        migrations.RunPython(rewrite_product_uom, migrations.RunPython.noop),
        migrations.RemoveConstraint("product", "ops_product_positive_pack_qty"),
        migrations.RemoveConstraint("igdeal", "ops_ig_deal_qty_positive"),
        migrations.RemoveConstraint("orderline", "ops_line_positive_qty"),
        migrations.RemoveConstraint("orderline", "ops_line_total_identity"),
        migrations.RemoveConstraint("inventorymove", "ops_move_nonzero"),
        migrations.RemoveConstraint("inventorymove", "ops_move_sign_discipline"),
        migrations.RemoveConstraint("inventorymove", "ops_move_value_sign"),
        migrations.RenameField("product", "pack_qty", "pieces_per_sale_unit"),
        migrations.RenameField("igdeal", "qty_packs", "qty_sale_units"),
        migrations.RenameField("orderline", "qty_packs", "qty_sale_units"),
        migrations.RenameField("inventorymove", "qty_delta_packs", "qty_delta_pieces"),
        migrations.RenameField("stockcountline", "qty_packs", "qty_pieces"),
        migrations.AlterField(
            "product", "uom", models.CharField(default="PC", max_length=2)
        ),
        migrations.AlterField(
            "product", "pieces_per_sale_unit", models.PositiveIntegerField()
        ),
        migrations.AddConstraint(
            "product", models.CheckConstraint(condition=Q(uom="PC"), name="ops_product_piece_uom")
        ),
        migrations.AddConstraint(
            "product", models.CheckConstraint(
                condition=Q(pieces_per_sale_unit__gte=1),
                name="ops_product_positive_pieces_per_sale_unit",
            )
        ),
        migrations.AddConstraint(
            "igdeal", models.CheckConstraint(
                condition=Q(qty_sale_units__isnull=True) | Q(qty_sale_units__gt=0),
                name="ops_ig_deal_qty_positive",
            )
        ),
        migrations.AddConstraint(
            "orderline", models.CheckConstraint(
                condition=Q(qty_sale_units__gt=0), name="ops_line_positive_qty"
            )
        ),
        migrations.AddConstraint(
            "orderline", models.CheckConstraint(
                condition=Q(
                    item_total_minor=models.F("qty_sale_units") * models.F("unit_price_minor")
                    - models.F("line_discount_minor")
                ),
                name="ops_line_total_identity",
            )
        ),
        migrations.AddConstraint(
            "inventorymove", models.CheckConstraint(
                condition=~Q(qty_delta_pieces=0) | Q(kind="opening", value_delta_twd=0),
                name="ops_move_nonzero",
            )
        ),
        migrations.AddConstraint(
            "inventorymove", models.CheckConstraint(
                condition=(
                    Q(kind="opening", qty_delta_pieces__gte=0)
                    | Q(kind__in=["received", "returned"], qty_delta_pieces__gt=0)
                    | Q(kind__in=["sold", "written_off"], qty_delta_pieces__lt=0)
                    | Q(kind="adjusted", qty_delta_pieces__lt=0)
                ),
                name="ops_move_sign_discipline",
            )
        ),
        migrations.AddConstraint(
            "inventorymove", models.CheckConstraint(
                condition=Q(value_delta_twd__isnull=True)
                | Q(qty_delta_pieces__gt=0, value_delta_twd__gte=0)
                | Q(qty_delta_pieces__lt=0, value_delta_twd__lte=0)
                | Q(kind="opening", qty_delta_pieces=0, value_delta_twd=0),
                name="ops_move_value_sign",
            )
        ),
        migrations.RunSQL(
            "ALTER VIEW ops_on_hand RENAME COLUMN qty_packs TO qty_pieces;",
            "ALTER VIEW ops_on_hand RENAME COLUMN qty_pieces TO qty_packs;",
        ),
        migrations.RunSQL(IG_TRIGGER_V2, IG_TRIGGER_V1),
    ]
