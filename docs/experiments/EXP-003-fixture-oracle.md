# EXP-003 — Offline fixture oracle and comparison

- **Date** 2026-11-25
- **Research question IDs** R02, R03, R13
- **Status** Passed for the offline fixture audit and comparison
- **Operator** Codex
- **Branch** `feature/1.4-fixture-oracle`
- **Software** CPython 3.12.3, GNU Make 4.3 and Git 2.43.0 locally. CI uses CPython 3.12.3 on the existing Ubuntu 24.04 runner.

## Hypothesis

Literal snapshots can represent the published v1, seed 42 workload at each checkpoint. A keyed comparison accepts equal snapshots in any row order and detects duplicate keys, absent or unexpected rows, and any changed value or timestamp.

## Preconditions

Run from a checkout of the ticket branch with the pinned interpreter on PATH as `python3`. The fixture inputs for this experiment are the [published schema, scenarios and reporting contract](../synthetic-workload.md) and the [row-parity protocol](../verification-plan.md#row-parity-and-deletion).

**Verified documentation, 2026-11-25.** CPython [3.12.3](https://www.python.org/downloads/release/python-3123/) includes [unittest discovery](https://docs.python.org/3.12/library/unittest.html#test-discovery) and ISO 8601 parsing with a [UTC Z suffix](https://docs.python.org/3.12/library/datetime.html#datetime.datetime.fromisoformat). The workflow pins [setup-python v6.2.0](https://github.com/actions/setup-python/releases/tag/v6.2.0) to `a309ff8b426b58ec0e2a45f0f869d46889d02405` and requests the exact patch version through its [version input](https://github.com/actions/setup-python/blob/v6.2.0/docs/advanced-usage.md#specifying-a-python-version).

**Decision.** Store the rows and report values as complete literal JSON snapshots. The validation path uses only the Python standard library. Future readers are responsible for exporting their observed rows into the documented canonical representation.

## Procedure

1. Read each business row in [expected.json](../../tests/fixtures/v1/expected.json) against the published table column order and scenario values. Check stable keys and values before and after each step. Check both timestamps on each insert and preserve creation time across updates.
2. Calculate each customer's order count from the order IDs and line totals from its items by hand. Compare both customer report rows at each step. Compare every field across S05 and S06.
3. Run the repository checks and comparison tests from the repository root.

   ```sh
   python3 --version
   make --version
   git --version
   make help check BASE=origin/main
   sh tests/repository-checks.sh
   make test-unit
   ```

4. Check the pull-request **Repository checks** workflow. Its unit test step uses the same target.

## Expected results

All seven literal snapshots match the specification. Both customers have exact order counts and item totals. Item 102 is present in S01 and S02 and absent from S03 onward. S05 and S06 have identical rows and timestamps. The suite passes when a matching result produces no diagnostics and each injected fault produces its specific diagnostic.

## Actual observations

Manual review checked both unchanged customer rows, the original order and payment rows, the item 102 insertion at T01, and the item 101 quantities and timestamp pairs `(T00,T00)` at S00–S01, `(T00,T02)` at S02–S04 and `(T00,T05)` at S05–S06. At S03 the entire row for item 102 disappears. At S04 order 30 belongs to customer 1, item 301 belongs to order 30, and payment 302 references order 30 for 400 cents. All three rows have both timestamps at T04. At S05 payment 303 references order 10 for 200 cents with both timestamps at T05. The earlier payment 301 and item 301 occupy separate tables. An independent comparison against transcribed specification tuples confirmed each column and timestamp at all seven steps and exact S05/S06 equality.

### Hand calculation

| Checkpoint | Customer 1 orders | Customer 1 item cents | Customer 2 orders | Customer 2 item cents |
| --- | --- | --- | --- | --- |
| S00 | 10 (1) | 2 × 300 = 600 | 20 (1) | 1 × 500 = 500 |
| S01 | 10 (1) | 2 × 300 + 1 × 500 = 1,100 | 20 (1) | 1 × 500 = 500 |
| S02 | 10 (1) | 3 × 300 + 1 × 500 = 1,400 | 20 (1) | 1 × 500 = 500 |
| S03 | 10 (1) | 3 × 300 = 900 after deleting item 102 | 20 (1) | 1 × 500 = 500 |
| S04 | 10, 30 (2) | 3 × 300 + 2 × 200 = 1,300 | 20 (1) | 1 × 500 = 500 |
| S05 | 10, 30 (2) | 4 × 300 + 2 × 200 = 1,600 | 20 (1) | 1 × 500 = 500 |
| S06 | 10, 30 (2) | 4 × 300 + 2 × 200 = 1,600 | 20 (1) | 1 × 500 = 500 |

Orders 10 and 30 count as two orders even if order 10 has several items. Payment 303 has no effect on either aggregate. Replay leaves the S04 business rows at T04, the latest item 101 update and payment 303 at T05, and the rest of the snapshot unchanged.

Local repository checks passed and the shell regression suite confirmed all five rejection paths. `make test-unit` reported `Ran 14 tests` and `OK`. The negative cases assert the full output, including these examples from the injected faults.

```text
order_items: unequal item_id=101 quantity: expected 3, got 2
orders: unequal order_id=30 updated_at: expected '2026-01-01T00:04:00Z', got '2026-01-01T00:06:00Z'
order_items: duplicate expected key item_id=101
order_items: duplicate actual key item_id=201
order_items: missing key item_id=201
order_items: extra key item_id=102
report: unequal customer_id=1 item_total_cents: expected 1600, got 1800
report: unequal customer_id=2 order_count: expected 1, got 2
```

## Evidence artifacts

The [expected rows](../../tests/fixtures/v1/expected.json) and [unit assertions](../../tests/unit/test_fixture_oracle.py) retain the synthetic evidence and negative controls. The ticket pull request records the hosted workflow result for the reviewed commit. [GitHub issue #22](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/22)

## Interpretation

The comparator detects wrong values and a missing row paired with an extra row even when row counts agree. It reports duplicate row keys before matching values in the affected relation. The report comparison also checks customer keys and counts.

## Limitations and follow-up

R02, R03 and R13 remain open pending runtime verification. The oracle covers committed checkpoint expectations for the four business tables and the report. Future source experiments must observe transaction visibility and verify S04 receipt behavior independently. Actual Gold values still require a materialized pipeline and an independent read.
