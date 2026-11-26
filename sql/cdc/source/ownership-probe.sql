-- Native PG16 permission experiment. Optionally retain only the scoped publication.
-- Future connector onboarding must choose its own commit and grant boundaries.
BEGIN;

SELECT NOT EXISTS (SELECT FROM pg_publication WHERE pubname = :'publication')
       AND (SELECT count(*) = 4 AND bool_and(
                c.relowner = 'source_fixture_owner'::regrole AND c.relreplident = 'd'
                AND EXISTS (SELECT FROM pg_index AS i WHERE i.indrelid = c.oid
                            AND i.indisprimary AND i.indisvalid)
            )
            FROM pg_class AS c
            WHERE c.relnamespace = 'fixture'::regnamespace AND c.relkind = 'r'
              AND c.relname IN ('customers', 'orders', 'order_items', 'payments'))
       AND NOT EXISTS (SELECT FROM pg_publication_namespace)
       AND NOT EXISTS (SELECT FROM pg_inherits WHERE inhparent IN (
           'fixture.customers'::regclass, 'fixture.orders'::regclass,
           'fixture.order_items'::regclass, 'fixture.payments'::regclass
       ))
       AS baseline_ok \gset
\if :baseline_ok
\else
    DO $$ BEGIN RAISE EXCEPTION 'unexpected replication object or fixture owner/identity'; END $$;
\endif

-- Admin performs the owner transfers. The publisher receives no fixture-owner membership
-- and no CREATE on the fixture schema.
ALTER TABLE fixture.customers OWNER TO :"publisher";
ALTER TABLE fixture.orders OWNER TO :"publisher";
ALTER TABLE fixture.order_items OWNER TO :"publisher";
ALTER TABLE fixture.payments OWNER TO :"publisher";
GRANT CREATE ON DATABASE source_lab TO :"publisher";
SET LOCAL SESSION AUTHORIZATION :"publisher";
CREATE PUBLICATION :"publication" FOR TABLE
    fixture.customers, fixture.orders, fixture.order_items, fixture.payments;
RESET SESSION AUTHORIZATION;
REVOKE CREATE ON DATABASE source_lab FROM :"publisher";
SELECT oid, pubname, pg_get_userbyid(pubowner) FROM pg_publication WHERE pubname = :'publication';
SELECT pubname, schemaname, tablename
FROM pg_publication JOIN pg_publication_tables USING (pubname)
WHERE pubname = :'publication' ORDER BY tablename;
SELECT has_database_privilege(:'publisher', 'source_lab', 'CREATE'),
       pg_has_role(:'publisher', 'source_fixture_owner', 'MEMBER');

-- Use reserved synthetic keys on the empty regression clone. Roll back all changes.
SAVEPOINT writer_probes;
SET LOCAL SESSION AUTHORIZATION source_fixture_writer;
INSERT INTO fixture.customers VALUES (901, 'C901', 'Ownership test', '2026-02-01 00:00:00+00', '2026-02-01 00:00:00+00');
INSERT INTO fixture.orders VALUES (910, 901, 'O910', 'open', '2026-02-01 00:00:00+00', '2026-02-01 00:00:00+00');
INSERT INTO fixture.order_items VALUES (911, 910, 1, 'Test', 1, 0, '2026-02-01 00:00:00+00', '2026-02-01 00:00:00+00');
INSERT INTO fixture.payments VALUES (912, 910, 'P912', 0, '2026-02-01 00:00:00+00', '2026-02-01 00:00:00+00');
INSERT INTO fixture.scenario_receipts VALUES ('v1', 0, 'S04', repeat('a', 64));
UPDATE fixture.order_items SET quantity = 2 WHERE item_id = 911;
WITH deleted AS (DELETE FROM fixture.order_items WHERE item_id = 911 RETURNING *)
SELECT item_id, quantity FROM deleted;
RESET SESSION AUTHORIZATION;

SET LOCAL SESSION AUTHORIZATION source_fixture_reader;
SELECT c.customer_id, o.order_id, p.payment_id, r.scenario_id, i.item_id IS NULL
FROM fixture.customers AS c
JOIN fixture.orders AS o USING (customer_id)
JOIN fixture.payments AS p USING (order_id)
LEFT JOIN fixture.order_items AS i USING (order_id)
CROSS JOIN fixture.scenario_receipts AS r
WHERE c.customer_id = 901 AND o.order_id = 910 AND p.payment_id = 912 AND r.seed = 0;
RESET SESSION AUTHORIZATION;

\if :keep_publication
    -- Restore reset authority before committing. Reestablish the explicit read grant
    -- because PostgreSQL rewrites ACLs during owner changes.
    ROLLBACK TO SAVEPOINT writer_probes;
    ALTER TABLE fixture.customers OWNER TO source_fixture_owner;
    ALTER TABLE fixture.orders OWNER TO source_fixture_owner;
    ALTER TABLE fixture.order_items OWNER TO source_fixture_owner;
    ALTER TABLE fixture.payments OWNER TO source_fixture_owner;
    GRANT SELECT ON fixture.customers, fixture.orders, fixture.order_items, fixture.payments TO :"publisher";
    COMMIT;
\else
    ROLLBACK;
\endif
