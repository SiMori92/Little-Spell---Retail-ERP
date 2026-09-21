"""Database roles and grants — BUILD_TASK §3.1, KICKSTART §1.

The segregation of duties is enforced by Postgres, not by the application. Agent 2
(`acct_writer`) can read everything Agent 1 (`ops_writer`) wrote and change none of
it. That is the audit relationship, and it holds whether or not the next script
written at midnight remembers it.

Because KICKSTART §1 replaces the two-schema design with two Django APPS, the
namespaces are table PREFIXES (`ops_*`, `acct_*`) in one schema, and grants are made
by prefix.

The SQL lives here rather than inline in the migration because it is convergent and
idempotent — it is re-applied by `manage.py apply_table_grants` after every migration
that creates tables, and both callers must never drift apart. It is grant state, not
schema history.

ONE LIMITATION, STATED PLAINLY: `ALTER DEFAULT PRIVILEGES` cannot filter by table
name prefix. It can only say "every future table in this schema". So it carries the
SELECT floor that is correct for BOTH readers, and the prefix-specific WRITE grants
are applied by the loop in `TABLE_GRANTS_SQL`, which must be re-run after each
migration that adds tables. `apply_table_grants` is that step; the Railway pre-deploy
command runs it straight after `migrate`.
"""

ROLES = ("ops_writer", "acct_writer", "reporter")

# ---------------------------------------------------------------------------
# 1. The roles themselves.
# ---------------------------------------------------------------------------
# No passwords are set here. A password in a migration is a password in Git.
# These roles cannot connect until a password is set out of band:
#     ALTER ROLE ops_writer WITH PASSWORD '...';
CREATE_ROLES_SQL = """
DO $$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['ops_writer', 'acct_writer', 'reporter'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I LOGIN', r);
        END IF;
    END LOOP;
END
$$;

GRANT USAGE ON SCHEMA public TO ops_writer, acct_writer, reporter;
"""

# ---------------------------------------------------------------------------
# 2. Default privileges, so FUTURE tables inherit the intended grants.
# ---------------------------------------------------------------------------
# FOR ROLE current_user: default privileges attach to the role that CREATES the
# object, which is whichever role runs `migrate`.
DEFAULT_PRIVILEGES_SQL = """
DO $$
DECLARE owner_role text := current_user;
BEGIN
    -- The SELECT floor. Correct for both readers on every future table, which is
    -- why it is the part that ALTER DEFAULT PRIVILEGES can express.
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
        'GRANT SELECT ON TABLES TO acct_writer, reporter', owner_role);

    -- Writers need the sequences behind their serial primary keys.
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
        'GRANT USAGE, SELECT ON SEQUENCES TO ops_writer, acct_writer', owner_role);
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
        'GRANT SELECT ON SEQUENCES TO reporter', owner_role);
END
$$;
"""

DROP_DEFAULT_PRIVILEGES_SQL = """
DO $$
DECLARE owner_role text := current_user;
BEGIN
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
        'REVOKE SELECT ON TABLES FROM acct_writer, reporter', owner_role);
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
        'REVOKE USAGE, SELECT ON SEQUENCES FROM ops_writer, acct_writer', owner_role);
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
        'REVOKE SELECT ON SEQUENCES FROM reporter', owner_role);
END
$$;
"""

# ---------------------------------------------------------------------------
# 3. Prefix grants on tables that exist NOW. Re-run after every migration.
# ---------------------------------------------------------------------------
TABLE_GRANTS_SQL = """
DO $$
DECLARE t record;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        -- reporter reads everything and writes nothing, anywhere.
        EXECUTE format('GRANT SELECT ON public.%I TO reporter', t.tablename);

        IF t.tablename LIKE 'ops\\_%' THEN
            EXECUTE format(
                'GRANT SELECT, INSERT, UPDATE ON public.%I TO ops_writer', t.tablename);
            -- Agent 2 reads Agent 1's world and can change none of it.
            EXECUTE format('GRANT SELECT ON public.%I TO acct_writer', t.tablename);

        ELSIF t.tablename LIKE 'acct\\_%' THEN
            EXECUTE format(
                'GRANT SELECT, INSERT, UPDATE ON public.%I TO acct_writer', t.tablename);
            -- Agent 1 must never write a journal line. It does not read the books either.
            EXECUTE format('REVOKE ALL ON public.%I FROM ops_writer', t.tablename);

        ELSE
            -- Framework and platform tables (auth_*, django_*, core_*): read-only to
            -- both writers. Neither agent has business editing platform state.
            EXECUTE format('GRANT SELECT ON public.%I TO acct_writer', t.tablename);
            EXECUTE format('GRANT SELECT ON public.%I TO ops_writer', t.tablename);
        END IF;
    END LOOP;
END
$$;

-- =========================================================================
-- SLICE B, NOT SLICE 0 -- the line that makes the books defensible:
--
--   REVOKE UPDATE, DELETE ON acct_journalentry, acct_journalline
--     FROM PUBLIC, ops_writer, acct_writer;
--
-- It is deliberately ABSENT here. Those tables do not exist yet; running it now
-- would simply error. It belongs in the SAME Slice B migration that creates the
-- journal tables, so the tables are never writable for even one deploy.
-- Corrections are reversing entries -- never an UPDATE, never a DELETE.
-- Recorded in docs/SCHEMA_RULINGS.md so it is not lost between slices.
-- =========================================================================
"""

REVOKE_TABLE_GRANTS_SQL = """
DO $$
DECLARE t record;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format(
            'REVOKE ALL ON public.%I FROM ops_writer, acct_writer, reporter', t.tablename);
    END LOOP;
END
$$;

REVOKE USAGE ON SCHEMA public FROM ops_writer, acct_writer, reporter;
"""

# The roles are deliberately NOT dropped on reverse. A role is a CLUSTER-wide
# object; a per-database migration that dropped it would yank it out from under
# every other database in the cluster, and would fail anyway while it still holds
# privileges elsewhere. Reversing this migration removes the PRIVILEGES it granted
# in THIS database, which is the full extent of what it granted.
