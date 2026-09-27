"""Slice U accounting quantity-dimension rename and whole-piece checks."""

from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Floor


class Migration(migrations.Migration):
    dependencies = [
        ("acct", "0006_remove_journalline_acct_line_one_side_and_more"),
        ("ops", "0011_piece_inventory_unit"),
    ]

    operations = [
        migrations.RemoveConstraint("wacposition", "acct_wac_nonnegative"),
        migrations.RemoveConstraint("journalline", "acct_line_one_side"),
        migrations.RenameField("wacposition", "qty_packs", "qty_pieces"),
        migrations.RenameField("journalline", "qty_delta_packs", "qty_delta_pieces"),
        migrations.AddConstraint(
            "wacposition", models.CheckConstraint(
                condition=Q(qty_pieces__gte=0, value_twd__gte=0), name="acct_wac_nonnegative"
            )
        ),
        migrations.AddConstraint(
            "wacposition", models.CheckConstraint(
                condition=Q(qty_pieces=Floor("qty_pieces")), name="acct_wac_whole_pieces"
            )
        ),
        migrations.AddConstraint(
            "journalline", models.CheckConstraint(
                condition=Q(debit__gte=0, credit__gte=0)
                & (
                    Q(debit__gt=0, credit=0)
                    | Q(credit__gt=0, debit=0)
                    | (
                        Q(debit=0, credit=0, source_ref__startswith="ops:opening-count|")
                        & (
                            Q(account_id="1231", sku__isnull=False, qty_delta_pieces=0)
                            | Q(account_id="3111", sku__isnull=False, qty_delta_pieces__isnull=True)
                        )
                    )
                ),
                name="acct_line_one_side",
            )
        ),
        migrations.AddConstraint(
            "journalline", models.CheckConstraint(
                condition=Q(qty_delta_pieces__isnull=True)
                | Q(qty_delta_pieces=Floor("qty_delta_pieces")),
                name="acct_line_whole_pieces",
            )
        ),
    ]
