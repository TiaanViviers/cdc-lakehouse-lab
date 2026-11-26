# EXP-013 — Independent CDC checkpoint parity

- **Date** 2026-11-26
- **Research questions** R02, R03, R13
- **Status** Offline checks passed. Build-specific validation awaits ticket 2.1.
- **Operator** Codex
- **Tested revision** `31c2889` on `d9de734a14ad33c75025cf564ada801461bde516`
- **Software** CPython 3.12.3 and its standard library for offline checks. Source PostgreSQL 16.16 was verified in Phase 1. Consumer PG18.4 and bundled extensions are candidate versions from [EXP-010](EXP-010-phase-2-candidate-review.md).

## Hypothesis

Bounded independent reads at held fixture checkpoints can establish exact source and target content against the v1 oracle. A target read may match after its first observation. Identifying the lake snapshot behind that observation requires evidence from the selected reader.

## Preconditions and verified documentation

Use the v1 fixture with seed 42 and the published independent expectations. For live validation, use the selected ticket 2.1 build in the maintainer-scheduled isolated guest with the documented project and image identities. Record the exact consumer mapping, SQL column types and psql version before testing. Use source-local and consumer-local psql with their respective lab roles and no credential arguments. Hold later writes until the read window ends. [Synthetic workload](../synthetic-workload.md) · [Phase 2 runtime conventions](../../backlog/phase-2.md#parallel-development-and-runtime-conventions)

Reviewed on 2026-11-26. PostgreSQL 16 documents CSV and script-error handling in psql, plus statement and idle-in-transaction timeout controls. PostgreSQL 18 documents read-only repeatable-read transactions. Python 3.12 documents subprocess timeouts and child cleanup. The extension's behavior under those transaction settings requires a trial. [PG16 psql](https://www.postgresql.org/docs/16/app-psql.html) · [PG16 client settings](https://www.postgresql.org/docs/16/runtime-config-client.html) · [PG18 transaction modes](https://www.postgresql.org/docs/18/sql-set-transaction.html) · [Python 3.12 subprocess](https://docs.python.org/3.12/library/subprocess.html#subprocess.run)

## Projection and evidence decisions

- The source projection uses `fixture.{customers,orders,order_items,payments}`. The target caller supplies four distinct schema/table pairs whose named columns implement the v1 projection. One-table validation uses the same SQL and row-normalization primitives with the actual probe columns. The adapter requests explicit columns, orders by the stable primary key and asks for at most 33 rows per relation. The 33rd row rejects the capture before report computation or evidence publication. The offline iterable path consumes at most 33 rows too.
- Integers use native integers or base-10 integer text. Whole-valued floats and booleans fail validation. Timestamp values require a timezone-aware datetime or ISO text with an explicit offset, and normalize to UTC with up to six fractional digits. Text values retain their content. Nulls fail the v1 non-null projection.
- Each side computes the report from its captured business rows. Count orders independently of the item sum, include every customer, and use the sum of quantity times unit cents over matched items. Payments are checked as full rows and contribute zero to the report. Source receipts stay in source diagnostics.
- Each psql call uses a fresh session and one requested read-only repeatable-read transaction. It sets UTC and ISO rendering and rolls back after the reads. The client has a wall-clock timeout and each server statement and idle transaction have a timeout. The subprocess wrapper keeps command arguments and raw stderr out of parity artifacts. Preserve reviewed server diagnostics separately for runtime failures.
- The source gets a single read with its own deadline. The target polls fresh sessions on keyed mismatch until the first exact read, a read error, or its deadline. Default budgets are 10 s for source, 60 s for target, and 500 ms between target attempts. Pass requires both sides to match independently. A late match fails even if its contents would have passed. A custom reader must enforce the remaining budget passed to it.
- A normalized snapshot carries UTC start and finish times, monotonic capture duration, and reader semantics. A build-specific reader can supply an attributed catalog snapshot ID through `Capture`. The PostgreSQL-facing adapter emits null for that field. PostgreSQL repeatable read alone establishes no shared DuckLake snapshot. Keep the hold point explicit and record any connector reader limitations with the observed build.

## Procedure

### Offline

```sh
python3 --version
python3 -m unittest discover -s tests/unit -p test_cdc_parity.py -v
make test-unit
make check BASE=origin/main
sh tests/repository-checks.sh
git diff origin/main --exit-code -- tests/fixture_oracle.py tests/fixtures/v1/expected.json
```

The unit suite constructs its own synthetic read results from the workload's documented DML. The fixture comparator opens the checked-in JSON for expected rows. For trial output, pass source and target read callbacks and write the results to a fresh hold-point subdirectory under `artifacts/EXP-013/<UTC-run-id>/` using `write_evidence`. That produces `source` and `target` JSON snapshots and diffs, plus `target-last-mismatch` when a poll finds stale rows. Overflow and other failed captures have a diff record without a snapshot.

### Selected build one-table check

1. Use the confirmed 2.1 setup in its scheduled window, or use its reviewed, redacted mapped-table CSV and exact projected column types if the evidence captures equivalent reads. Save image and extension identities, read role, exact SQL, column types, mapping and the observed rows at initial copy, insert, update and delete. Record catalog snapshot attribution only when the row reads can be tied to it. If the available probe omits a required type, record that gap and coordinate a narrowly scoped follow-up trial.
2. At each hold point use `read_projections(local_psql_command, {"probe": ((schema, table), columns, pk)}, 10)` on the actual mapped table. For replayed evidence, feed the actual psql CSV envelope through the same parsing path as the psql transport tests. Apply `normalize_rows("probe", capture.rows["probe"], columns, pk, integer_columns, timestamp_columns)` and use `tests.fixture_oracle.compare_rows` against the manually declared probe rows. Capture the same check at the source independently. Use separate phase and side labels in the evidence. Verify retained deletes and duplicates by key and confirm an intentionally wrong expected value emits a keyed diff.
3. Record whether the target accepted the read-only transaction, the observed runtime type/UTC representations, any timeout behavior and applicable snapshot identity. Rebase to current main with the accepted prerequisite, rerun checks and record the tested SHA before opening the PR. Ticket 2.6 owns four-table runtime validation.

## Expected results

S00–S06 produce empty diff lists on both sides. Altered rows produce phase- and side-labelled missing, duplicate, extra or unequal row differences. Overflow fails before a truncated result can be accepted. A missed target deadline preserves the latest mismatch and returns a timeout outcome. The selected build should produce the exact table types and rows recorded by ticket 2.1 within the declared read budget.

## Actual observations

The isolated parity suite passed 14 tests and the full suite passed 38. Repository checks passed, including all five deliberately failing controls. The oracle and expected JSON had zero diff from main. In the offline poll example, source and first target captures held the pre-delete state, and the second target capture matched S03. Source stayed `mismatch`, target returned `pass`, and the combined result remained failed.

| Control | Observed example |
| --- | --- |
| Exact checkpoint | `S03` source and target `pass` with `diffs: []` |
| Missing row | `after-delete/S03 target: payments: missing key payment_id=301` |
| Duplicate key | `after-delete/S03 target: orders: duplicate actual key order_id=10` |
| Retained delete | `after-delete/S03 target: order_items: extra key item_id=102` |
| Wrong value | `after-delete/S03 target: order_items: unequal item_id=101 unit_cents: expected 300, got 301` |
| Wrong timestamp | `after-delete/S03 target: customers: unequal customer_id=2 updated_at: expected '2026-01-01T00:00:00Z', got '2026-01-01T00:00:00.000001Z'` |
| Report drift | `initial/S00 source: report: unequal customer_id=1 order_count: expected 1, got 2` with exact business rows |
| Overflow | `initial/S00 target: customers: row overflow (limit 32)` |

The offset forms `2026-01-01 02:30:00+02:30` and `2025-12-31 19:00:00-05:00` both normalized to `2026-01-01T00:00:00Z`. The SQL transport test asserted the emitted read-only transaction, four ordered limits, a 1,500 ms SQL timeout and the final rollback. An offline sleeping subprocess returned `psql client deadline expired` with a 100 ms client budget. A fake monotonic clock exercised a 1.25 s target deadline with attempt budgets of 1.25 s and 0.25 s, one full interval and one clipped wait. A result arriving at the deadline was rejected.

## Evidence artifacts

The repository retains the [parity contract](../../scripts/cdc/parity/__init__.py), [psql adapter](../../scripts/cdc/parity/psql.py) and [offline test inputs and assertions](../../tests/unit/test_cdc_parity.py). The tables above summarize those offline observations. Selected-build evidence is pending.

## Interpretation, limitations and follow-up

Offline results establish independent snapshot and report comparison, bounded extraction at the reader boundary, and deadline and evidence handling. The SQL transaction assertion covered generated text. The subprocess timeout control exercised the local client boundary. Actual target SQL acceptance, server cancellation, mappings, rendered types and DuckLake snapshot semantics remain open pending [ticket 2.1](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/38). R02, R03 and R13 remain OPEN at their Phase 2 acceptance conditions. Ticket 2.9 owns reconciliation of the shared research register. [Ticket 2.3](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/40)
