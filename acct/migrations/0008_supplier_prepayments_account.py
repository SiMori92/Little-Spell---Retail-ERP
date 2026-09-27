"""Install R-2 account 1266, added to the founder-owned chart after Slice B's snapshot."""

from django.db import migrations


ACCOUNT = {
    "code": "1266",
    "name_en": "Prepayments to suppliers - PO deposits",
    "name_zh": "預付貨款",
    "type": "asset",
    "statement": "BS",
    "normal_balance": "debit",
    "statutory_code": "126",
    "tax_treatment": "n_a",
    "tax_regime": "both",
    "subledger": "vendor",
    "is_reserved": False,
    "is_contra": False,
    "is_closing_only": False,
    "active_from": "2026-09-27",
    "active_to": None,
}


def add_account(apps, schema_editor):
    Account = apps.get_model("acct", "Account")
    Account.objects.update_or_create(code="1266", defaults=ACCOUNT)


def remove_account(apps, schema_editor):
    apps.get_model("acct", "Account").objects.filter(code="1266").delete()


class Migration(migrations.Migration):
    dependencies = [("acct", "0007_piece_inventory_unit")]
    operations = [migrations.RunPython(add_account, remove_account)]
