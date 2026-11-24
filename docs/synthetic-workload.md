# Synthetic source workload — ticket 0.3

**Status: specification, 2026-11-24.** These are proposed Phase 1 fixtures, not observed CDC or Gold results. All names and records are invented for this lab; no external dataset or personal information is used. R02, R03 and R13 remain open until experiments verify snapshot, changes and cross-table consistency. No token entity is needed for this workload; Phase 6 will define its own synthetic contract.

## Fixed requirements

All IDs below are explicit positive integers, assigned by the fixture, not sequences. Monetary amounts are integer cents; quantities are positive integers. All columns are non-null except where stated. Primary keys are stable and never updated. Foreign keys use `ON DELETE RESTRICT`; delete children explicitly before parents in the same transaction. No cascading deletes or orphaned rows are expected. Natural keys are unique as indicated. Enforce nonnegative amounts, positive quantities and the listed status values. `created_at` is immutable; each changed row receives the scenario timestamp as `updated_at`. Both are UTC instants stored as PostgreSQL `timestamptz`, rendered as ISO 8601 UTC; no wall-clock calls. Transactions that fail leave every table unchanged.

| Table | Columns and constraints |
| --- | --- |
| customers | `customer_id` PK; `code` unique text; `name` text; `created_at`, `updated_at` |
| orders | `order_id` PK; `customer_id` FK customers; `order_ref` unique text; `status` text in `open`, `paid`; timestamps |
| order_items | `item_id` PK; `order_id` FK orders; `line_no` positive integer; `sku` text; `quantity` positive integer; `unit_cents` nonnegative integer; timestamps; unique (`order_id`, `line_no`) |
| payments | `payment_id` PK; `order_id` FK orders; `payment_ref` unique text; `amount_cents` nonnegative integer; timestamps |

No payment-total constraint is imposed: partial payments and unpaid orders are valid. Reporting below uses item totals, not payment sums, avoiding join multiplication. IDs and unique references do not imply commit or event ordering. Compare rows by primary key numerically and columns in the table order above; do not infer chronology from keys.

## Reproducible scenario contract

Fixture version `v1`, seed `42`, scenario IDs `S00`–`S06`. Seed is a reserved reproducibility identifier; v1 uses the literal values below, with no PRNG dependence. Execute in ID order on a disposable local source. Each scenario has one transaction unless otherwise specified. `T00` is `2026-01-01T00:00:00Z`; `T01` through `T06` are respectively one through six minutes later. A row written at Txx has both timestamps Txx on insert; updates preserve `created_at` and set `updated_at` to Txx.

- **S00 bootstrap (T00):** Insert customers `(1, C1, Ada)` and `(2, C2, Bo)`; orders `(10, 1, O10, open)` and `(20, 2, O20, paid)`; items `(101, 10, 1, A, 2, 300)` and `(201, 20, 1, B, 1, 500)`; payment `(301, 20, P301, 500)`. Insert parents before children. Values omit timestamps, which follow the rule above.
- **S01 insert (T01):** Insert item `(102, 10, 2, B, 1, 500)`.
- **S02 update (T02):** Change item 101 quantity from 2 to 3; leave its other values unchanged.
- **S03 delete (T03):** Delete item 102. The key must be absent, not a null-filled row; S01 and S03 cancel only its final presence.
- **S04 atomic multi-table (T04):** Insert order `(30, 1, O30, paid)`, item `(301, 30, 1, C, 2, 200)` and payment `(302, 30, P302, 400)` in one transaction. Item ID 301 and payment ID 301 are in different tables. No intermediate committed source state may contain only part of this transaction.
- **S05 concurrent (T05):** Two transactions start from S04. A updates item 101 quantity to 4; B inserts payment `(303, 10, P303, 200)`. Use a synchronization barrier and record evidence that both transactions are open before either commits; then commit A before B. Use disjoint rows and fixed timestamps. After both commits the result is deterministic. This tests concurrent activity, not conflict resolution or atomic visibility across replicated tables.
- **S06 replay (T06):** S06 identifies the test step; re-submit S04 as the idempotency key with the original S04 payload to the fixture runner. Contract: it recognizes the already committed S04 and creates no new receipt or database changes, including timestamps. A failed/ambiguous first attempt must be reconciled before retry; a naive repeated insert causing unique violations is not successful replay. Phase 1 must specify and test durable transactionally coupled scenario receipts; this fixture does not claim they exist today.

Reset is allowed only against explicitly identified disposable local source services. Clear fixture tables and any scenario receipts in FK-safe order in a transaction, then run S00; repeated reset yields precisely S00, independent of prior scenarios. Never apply reset to non-disposable databases. Test invalid foreign keys, duplicate references, restricted parent deletion and rollback of S04 before commit: each must leave the previous committed state intact. A crash around commit and replay must not duplicate effects.

## Expected states and reporting oracle

The notation lists complete non-timestamp values in the column order in the schema; timestamp pairs are given below. A dash means no row. The state after S00 is exactly its inserted rows. Each following state is S00 plus these cumulative changes:

| Checkpoint | Changes relative to S00 |
| --- | --- |
| S01 | add item `(102, 10, 2, B, 1, 500)` at T01 |
| S02 | S01 plus item 101 quantity 3, updated T02 |
| S03 | S02 less item 102 |
| S04 | S03 plus order 30, item 301 and payment 302 as specified above, all at T04 |
| S05 | S04 plus item 101 quantity 4, updated T05, and payment 303 at T05 |
| S06 | identical to S05, including timestamps |

All S00 rows retain `(created_at, updated_at) = (T00, T00)` except item 101, whose timestamp pair after S02–S04 is `(T00, T02)` and after S05–S06 is `(T00, T05)`. Inserted rows retain their insertion timestamp for both fields. S03 deletes item 102 completely. At S06 keys are customers `{1,2}`, orders `{10,20,30}`, items `{101,201,301}`, payments `{301,302,303}`; every other key is absent.

A proposed Gold report groups **all orders** by customer and sums `quantity × unit_cents` over items, separately counting orders. The expected report at each checkpoint is:

| Checkpoint | Customer 1 orders | Customer 1 cents | Customer 2 orders | Customer 2 cents |
| --- | ---: | ---: | ---: | ---: |
| S00 | 1 | 600 | 1 | 500 |
| S01 | 1 | 1,100 | 1 | 500 |
| S02 | 1 | 1,400 | 1 | 500 |
| S03 | 1 | 900 | 1 | 500 |
| S04 | 2 | 1,300 | 1 | 500 |
| S05 | 2 | 1,600 | 1 | 500 |
| S06 | 2 | 1,600 | 1 | 500 |

For example, S06 customer 1 totals 4 × 300 + 2 × 200 = 1,600 cents. Payment amounts do not change this report. Include customers without orders with zero count and amount in future tests.

At each checkpoint, compare the full expected and actual rows in both directions by table and PK, including every value and UTC timestamp; report missing, extra and unequal rows separately. Compare the exact grouped report to both customers’ expected values at each checkpoint above. For CDC, capture a stable source boundary, wait for a documented convergence condition, then compare independently read Bronze with the corresponding complete source state, including deleted-key absence. An LSN or count alone is not parity; source transaction atomicity does not establish cross-table lake snapshot atomicity (R13). Retain query output and boundary evidence in the relevant experiment record.

## Phase 1 decisions still open

Choose the receipt schema and reconciliation protocol, fixture runner interface, concurrency synchronization mechanism, exact SQL migrations and reset guard. Establish supported PostgreSQL and CDC versions through ticket 0.1. Decide how source boundaries are captured and how intermediate cross-table visibility is measured; do not claim a consistent lake cutoff before testing it. Exact SQL syntax and runtime compatibility remain unverified here.
