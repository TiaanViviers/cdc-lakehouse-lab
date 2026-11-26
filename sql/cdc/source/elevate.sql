-- DuckPipe 86d5c24 performs CREATE PUBLICATION, ALTER PUBLICATION and ALTER TABLE.
BEGIN;
SELECT EXISTS (SELECT FROM pg_roles WHERE rolname = :'publisher' AND oid = :'created_role_oid'::oid)
       AND NOT EXISTS (SELECT FROM pg_replication_slots)
       AND NOT EXISTS (SELECT FROM pg_publication)
       AND (SELECT count(*) = 4 AND bool_and(relowner = 'source_fixture_owner'::regrole
                                            AND relreplident = 'd' AND relkind = 'r')
            FROM pg_class WHERE oid IN ('fixture.customers'::regclass, 'fixture.orders'::regclass,
                'fixture.order_items'::regclass, 'fixture.payments'::regclass))
       AND NOT EXISTS (SELECT FROM pg_inherits WHERE inhparent IN (
                'fixture.customers'::regclass, 'fixture.orders'::regclass,
                'fixture.order_items'::regclass, 'fixture.payments'::regclass))
       AS ready \gset
\if :ready
\else
    DO $$ BEGIN RAISE EXCEPTION 'publisher elevation requires the pristine four-table enrollment'; END $$;
\endif
ALTER TABLE fixture.customers OWNER TO :"publisher";
ALTER TABLE fixture.orders OWNER TO :"publisher";
ALTER TABLE fixture.order_items OWNER TO :"publisher";
ALTER TABLE fixture.payments OWNER TO :"publisher";
GRANT CREATE ON DATABASE source_lab TO :"publisher";
COMMIT;
