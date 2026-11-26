-- Catalog and SQL permissions as the publisher. Network authentication is tested from a peer.
BEGIN;
SET LOCAL SESSION AUTHORIZATION :"publisher";

SELECT * FROM fixture.customers LIMIT 0;
SELECT * FROM fixture.orders LIMIT 0;
SELECT * FROM fixture.order_items LIMIT 0;
SELECT * FROM fixture.payments LIMIT 0;

DO $$
DECLARE
    probe record;
BEGIN
    FOR probe IN SELECT * FROM (VALUES
        ('receipt read', 'SELECT * FROM fixture.scenario_receipts LIMIT 0'),
        ('receipt write', 'DELETE FROM fixture.scenario_receipts WHERE false'),
        ('enrollment read', 'SELECT * FROM fixture.installation LIMIT 0'),
        ('enrollment write', 'DELETE FROM fixture.installation WHERE false'),
        ('business write', 'UPDATE fixture.order_items SET quantity = 2 WHERE false'),
        ('business DDL', 'ALTER TABLE fixture.customers ADD COLUMN unwanted integer'),
        ('schema CREATE', 'CREATE TABLE fixture.unwanted (id integer)'),
        ('guarded reset', 'SELECT fixture.cleanup(false, NULL)'),
        ('fixture owner membership', 'SET ROLE source_fixture_owner')
    ) AS probes(label, command)
    LOOP
        BEGIN
            EXECUTE probe.command;
            RAISE EXCEPTION 'publisher unexpectedly allowed %', probe.label;
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'publisher denied % (%): %', probe.label, SQLSTATE, SQLERRM;
        END;
    END LOOP;
END
$$;
ROLLBACK;
