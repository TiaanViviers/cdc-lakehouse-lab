SET SESSION AUTHORIZATION source_fixture_reader;
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL DateStyle = 'ISO, YMD';

SELECT 'customers', coalesce(json_agg(c ORDER BY c.customer_id), '[]') FROM fixture.customers AS c;
SELECT 'orders', coalesce(json_agg(o ORDER BY o.order_id), '[]') FROM fixture.orders AS o;
SELECT 'order_items', coalesce(json_agg(i ORDER BY i.item_id), '[]') FROM fixture.order_items AS i;
SELECT 'payments', coalesce(json_agg(p ORDER BY p.payment_id), '[]') FROM fixture.payments AS p;
SELECT 'scenario_receipts', coalesce(json_agg(r ORDER BY r.fixture_version, r.seed, r.scenario_id), '[]')
FROM fixture.scenario_receipts AS r;

COMMIT;
