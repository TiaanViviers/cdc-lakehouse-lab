BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL DateStyle = 'ISO, YMD';

WITH
    customers AS (SELECT * FROM fixture.customers ORDER BY customer_id LIMIT 33),
    orders AS (SELECT * FROM fixture.orders ORDER BY order_id LIMIT 33),
    items AS (SELECT * FROM fixture.order_items ORDER BY item_id LIMIT 33),
    payments AS (SELECT * FROM fixture.payments ORDER BY payment_id LIMIT 33),
    receipts AS (
        SELECT r.*, r.xmin::text AS tuple_xid FROM fixture.scenario_receipts AS r
        ORDER BY fixture_version, seed, scenario_id LIMIT 33
    ),
    report AS (
        SELECT customer_id,
               (SELECT count(*) FROM orders AS o WHERE o.customer_id = c.customer_id) AS order_count,
               coalesce((SELECT sum(i.quantity::numeric * i.unit_cents)
                         FROM items AS i JOIN orders AS o USING (order_id)
                         WHERE o.customer_id = c.customer_id), 0) AS item_total_cents
        FROM customers AS c
    )
SELECT json_build_object(
    'customers', coalesce((SELECT json_agg(c ORDER BY customer_id) FROM customers AS c), '[]'),
    'orders', coalesce((SELECT json_agg(o ORDER BY order_id) FROM orders AS o), '[]'),
    'order_items', coalesce((SELECT json_agg(i ORDER BY item_id) FROM items AS i), '[]'),
    'payments', coalesce((SELECT json_agg(p ORDER BY payment_id) FROM payments AS p), '[]'),
    'report', coalesce((SELECT json_agg(g ORDER BY customer_id) FROM report AS g), '[]'),
    'receipts', coalesce((SELECT json_agg(r ORDER BY fixture_version, seed, scenario_id)
                          FROM receipts AS r), '[]')
);
COMMIT;
