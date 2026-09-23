"""Derived on-hand and an ops-event period admission lock.

The journal-line period lock in build-plan §3.4 remains Slice B: no journal table
exists in Slice A, and creating one here would violate the slice boundary.
"""

from django.db import migrations


VIEW_SQL = """
CREATE VIEW ops_on_hand AS
SELECT product_id AS sku, SUM(qty_delta_packs)::bigint AS qty_packs
FROM ops_inventorymove
GROUP BY product_id;
GRANT SELECT ON ops_on_hand TO ops_writer, acct_writer, reporter;
"""

LOCK_SQL = """
CREATE FUNCTION ops_reject_closed_event_period() RETURNS trigger AS $$
DECLARE p text;
DECLARE period_status text;
BEGIN
    p := to_char(NEW.occurred_at AT TIME ZONE 'Asia/Taipei', 'YYYY-MM');
    SELECT status INTO period_status FROM ops_opsperiod WHERE period = p FOR SHARE;
    IF period_status = 'CLOSED' THEN
        RAISE EXCEPTION 'ops period % is CLOSED', p;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER ops_event_period_lock
BEFORE INSERT OR UPDATE OF occurred_at ON ops_ledgerevent
FOR EACH ROW EXECUTE FUNCTION ops_reject_closed_event_period();

CREATE FUNCTION ops_require_dispatch_evidence() RETURNS trigger AS $$
BEGIN
    IF NEW.event_type IN ('order.shipped', 'order.cogs_relieved') THEN
        IF NEW.entity_table <> 'ops.order' OR NOT EXISTS (
            SELECT 1 FROM ops_shipment
            WHERE order_id = NEW.entity_id AND status = 'dispatched' AND ship_date IS NOT NULL
        ) THEN
            RAISE EXCEPTION '% requires dispatched shipment with ship_date', NEW.event_type;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER ops_event_dispatch_evidence
BEFORE INSERT OR UPDATE OF event_type, entity_table, entity_id ON ops_ledgerevent
FOR EACH ROW EXECUTE FUNCTION ops_require_dispatch_evidence();
"""


class Migration(migrations.Migration):
    dependencies = [("ops", "0001_initial"), ("core", "0002_database_roles")]

    operations = [
        migrations.RunSQL(VIEW_SQL, "DROP VIEW IF EXISTS ops_on_hand;"),
        migrations.RunSQL(
            LOCK_SQL,
            "DROP TRIGGER IF EXISTS ops_event_dispatch_evidence ON ops_ledgerevent; "
            "DROP FUNCTION IF EXISTS ops_require_dispatch_evidence(); "
            "DROP TRIGGER IF EXISTS ops_event_period_lock ON ops_ledgerevent; "
            "DROP FUNCTION IF EXISTS ops_reject_closed_event_period();",
        ),
    ]
