-- Reduce DDL/DML authority after registration. Leave the connector's replica identity in place.
BEGIN;
SELECT (SELECT count(*) = 4 AND bool_and(c.relowner = :'created_role_oid'::oid
                                       AND c.relreplident = 'f')
        FROM pg_class AS c WHERE c.oid IN ('fixture.customers'::regclass, 'fixture.orders'::regclass,
            'fixture.order_items'::regclass, 'fixture.payments'::regclass))
       AND EXISTS (SELECT FROM pg_roles WHERE rolname = :'publisher' AND oid = :'created_role_oid'::oid)
       AND EXISTS (SELECT FROM pg_publication WHERE pubname = :'publication' AND pubowner = :'created_role_oid'::oid)
       AS registered \gset
\if :registered
\else
    DO $$ BEGIN RAISE EXCEPTION 'publisher reduction requires four registered FULL identities'; END $$;
\endif
ALTER TABLE fixture.customers OWNER TO source_fixture_owner;
ALTER TABLE fixture.orders OWNER TO source_fixture_owner;
ALTER TABLE fixture.order_items OWNER TO source_fixture_owner;
ALTER TABLE fixture.payments OWNER TO source_fixture_owner;
GRANT SELECT ON fixture.customers, fixture.orders, fixture.order_items, fixture.payments TO :"publisher";
REVOKE CREATE ON DATABASE source_lab FROM :"publisher";
COMMIT;
