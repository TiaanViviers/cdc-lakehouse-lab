BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL timezone = 'UTC';
SHOW transaction_read_only;
SELECT order_id, customer_id, status FROM :"schema".orders WHERE order_id = 30;
SELECT item_id, order_id, quantity FROM :"schema".order_items WHERE item_id IN (102, 301)
ORDER BY item_id;
SELECT payment_id, order_id, amount_cents FROM :"schema".payments WHERE payment_id = 302;
ROLLBACK;
