"""Load the 74-code, non-transactional snapshot of ../state/coa.csv.

The source is read-only and lives outside the deployment repo. The snapshot was
made from its SHA-256 c282a2bc5b7d24fd0b0b8c11fe854ec1d619c7501ae4e34de09ac3fa02de4a20.
"""

import json
from pathlib import Path

from django.db import migrations


def load_accounts(apps, schema_editor):
    Account = apps.get_model("acct", "Account")
    data = json.loads((Path(__file__).resolve().parents[1] / "data" / "coa_snapshot.json").read_text(encoding="utf-8"))
    assert data["source_sha256"] == "c282a2bc5b7d24fd0b0b8c11fe854ec1d619c7501ae4e34de09ac3fa02de4a20"
    assert len(data["rows"]) == 74
    for row in data["rows"]:
        for key in ("is_reserved", "is_contra", "is_closing_only"):
            row[key] = row[key] == "true"
        row["code"] = row.pop("account_code")
        row["name_en"] = row.pop("account_name_en")
        row["name_zh"] = row.pop("account_name_zh")
        for key in ("active_from", "active_to", "tax_treatment"):
            row[key] = row[key] or None
        Account.objects.create(**row)


def unload_accounts(apps, schema_editor):
    apps.get_model("acct", "Account").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("acct", "0001_initial")]
    operations = [migrations.RunPython(load_accounts, unload_accounts)]
