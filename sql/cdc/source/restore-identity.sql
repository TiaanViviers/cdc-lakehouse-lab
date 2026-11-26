BEGIN;
SELECT EXISTS (SELECT FROM pg_roles WHERE rolname = :'publisher' AND oid = :'created_role_oid'::oid AND NOT rolcanlogin)
       AND NOT EXISTS (SELECT FROM pg_publication)
       AND NOT EXISTS (SELECT FROM pg_replication_slots)
       AND (SELECT count(*) = 4 AND bool_and(relowner = 'source_fixture_owner'::regrole AND relreplident = 'f')
            FROM pg_class WHERE oid IN ('fixture.customers'::regclass, 'fixture.orders'::regclass,
                'fixture.order_items'::regclass, 'fixture.payments'::regclass))
       AS restore \gset
\if :restore
\else
    DO $$ BEGIN RAISE EXCEPTION 'replica identity restore requires quiescent cleaned enrollment'; END $$;
\endif
ALTER TABLE fixture.customers REPLICA IDENTITY DEFAULT;
ALTER TABLE fixture.orders REPLICA IDENTITY DEFAULT;
ALTER TABLE fixture.order_items REPLICA IDENTITY DEFAULT;
ALTER TABLE fixture.payments REPLICA IDENTITY DEFAULT;
COMMIT;
