-- Acceptance data only. IDs and timestamps are separate from v1 S00–S06.
SET SESSION AUTHORIZATION source_fixture_writer;
BEGIN;
SET LOCAL TIME ZONE 'UTC';
INSERT INTO fixture.customers VALUES (901, 'C901', 'Schema test', '2026-02-01', '2026-02-01');
INSERT INTO fixture.orders VALUES (910, 901, 'O910', 'open', '2026-02-01', '2026-02-01');
INSERT INTO fixture.order_items VALUES (911, 910, 1, 'Test', 1, 0, '2026-02-01', '2026-02-01');
INSERT INTO fixture.payments VALUES (912, 910, 'P912', 0, '2026-02-01', '2026-02-01');
INSERT INTO fixture.scenario_receipts VALUES ('v1', 0, 'S04', repeat('a', 64));
UPDATE fixture.order_items SET quantity = 2, updated_at = '2026-02-02' WHERE item_id = 911;
INSERT INTO fixture.order_items VALUES (913, 910, 2, 'Test', 1, 0, '2026-02-01', '2026-02-01');
DELETE FROM fixture.order_items WHERE item_id = 913;
COMMIT;
