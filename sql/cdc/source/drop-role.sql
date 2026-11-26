BEGIN;
SELECT r.oid = :'created_role_oid'::oid AND NOT r.rolcanlogin AND r.rolreplication
       AND NOT EXISTS (SELECT FROM pg_replication_slots)
       AND NOT EXISTS (SELECT FROM pg_publication)
       AND NOT EXISTS (SELECT FROM pg_stat_activity WHERE usesysid = r.oid)
       AND NOT EXISTS (
           SELECT FROM pg_auth_members AS m WHERE r.oid IN (m.roleid, m.member)
       ) AS safe_role
FROM pg_roles AS r WHERE r.rolname = :'publisher' \gset
\if :safe_role
\else
    DO $$ BEGIN RAISE EXCEPTION 'refusing role drop: unexpected role, membership or replication objects'; END $$;
\endif

REVOKE SELECT ON fixture.customers, fixture.orders, fixture.order_items, fixture.payments FROM :"publisher";
REVOKE USAGE ON SCHEMA fixture FROM :"publisher";
REVOKE CONNECT ON DATABASE source_lab FROM :"publisher";
-- Fail on any unexpected owned object or privilege. Revokes roll back on failure.
DROP ROLE :"publisher";
COMMIT;
