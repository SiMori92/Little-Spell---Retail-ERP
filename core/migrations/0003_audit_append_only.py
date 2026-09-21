"""Make the audit log append-only in the DATABASE.

`AuditLogEntry.save`/`delete` already refuse, but application-level validation gets
bypassed by the next script written at midnight (BUILD_TASK §3.4). A trigger does not
care which client connected.
"""

from django.db import migrations

APPEND_ONLY = """
CREATE OR REPLACE FUNCTION core_audit_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'core_auditlogentry is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER core_auditlogentry_append_only
    BEFORE UPDATE OR DELETE ON core_auditlogentry
    FOR EACH ROW EXECUTE FUNCTION core_audit_append_only();
"""

DROP_APPEND_ONLY = """
DROP TRIGGER IF EXISTS core_auditlogentry_append_only ON core_auditlogentry;
DROP FUNCTION IF EXISTS core_audit_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0002_database_roles")]

    operations = [
        migrations.RunSQL(sql=APPEND_ONLY, reverse_sql=DROP_APPEND_ONLY),
    ]
