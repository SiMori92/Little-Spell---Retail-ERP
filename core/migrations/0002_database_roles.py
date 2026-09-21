"""Database roles and grants — a MIGRATION, not a manual step.

A manual step is a step that gets skipped when a database is rebuilt. Putting the
roles in a migration means the UAT database, a restored backup and a CI database all
get the same segregation without anybody remembering to apply it.

Requires the migrating role to hold CREATEROLE (or be superuser). On Railway and on
a stock local Postgres install it does. If it does not, this migration fails loudly,
which is correct — silently deploying without the segregation is the worse outcome.
"""

from django.db import migrations

from core import dbroles


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql=dbroles.CREATE_ROLES_SQL,
            reverse_sql=migrations.RunSQL.noop,  # roles are cluster-wide; see dbroles.py
        ),
        migrations.RunSQL(
            sql=dbroles.DEFAULT_PRIVILEGES_SQL,
            reverse_sql=dbroles.DROP_DEFAULT_PRIVILEGES_SQL,
        ),
        migrations.RunSQL(
            sql=dbroles.TABLE_GRANTS_SQL,
            reverse_sql=dbroles.REVOKE_TABLE_GRANTS_SQL,
        ),
    ]
