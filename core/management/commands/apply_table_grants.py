"""Re-apply the prefix-based table grants.

`ALTER DEFAULT PRIVILEGES` cannot filter by table-name prefix, so it carries only the
SELECT floor. The prefix-specific WRITE grants have to be re-applied after any
migration that creates tables. Run this straight after `migrate`, in the same
pre-deploy step. It is idempotent.
"""

from django.core.management.base import BaseCommand
from django.db import connection

from core import dbroles


class Command(BaseCommand):
    help = "Apply ops_*/acct_* prefix grants to all current tables. Idempotent."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute(dbroles.TABLE_GRANTS_SQL)
        self.stdout.write(self.style.SUCCESS("Table grants applied for %s." % ", ".join(dbroles.ROLES)))
