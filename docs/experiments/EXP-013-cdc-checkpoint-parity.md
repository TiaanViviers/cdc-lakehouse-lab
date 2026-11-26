# EXP-013 — Independent CDC checkpoint parity

- **Date** 2026-11-26
- **Research questions** R02, R03, R13
- **Status** Passed offline and on the selected build for the ticket 2.1 one-table scope.
- **Operator** Codex
- **Tested revision** `759a4637d15e0db4da7afeaaff4c11fc17fd7b44` on `500c213`, including merged ticket 2.1.
- **Software** CPython 3.12.3 and its standard library for offline checks. EXP-011 observed source PostgreSQL 16.16 and consumer PostgreSQL 18.4 with pg_duckdb 1.1.0, pg_ducklake 0.1.0, pg_duckpipe 1.0.0 and embedded DuckDB v1.5.1. [Observed versions and immutable image identities](EXP-011-remote-pg16-probe.md#actual-observations)

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
python3 -m unittest discover -s tests/unit -p 'test_cdc_parity*.py' -v
sha256sum -c docs/experiments/evidence/EXP-011.sha256
make test-unit
make check BASE=origin/main
sh tests/repository-checks.sh
git diff origin/main --exit-code -- tests/fixture_oracle.py tests/fixtures/v1/expected.json
```

The unit suite constructs its own synthetic read results from the workload's documented DML. The fixture comparator opens the checked-in JSON for expected rows. For trial output, pass source and target read callbacks and write the results to a fresh hold-point subdirectory under `artifacts/EXP-013/<UTC-run-id>/` using `write_evidence`. That produces `source` and `target` JSON snapshots and diffs, plus `target-last-mismatch` when a poll finds stale rows. Overflow and other failed captures have a diff record without a snapshot.

### Selected build one-table check

1. Use the confirmed 2.1 setup in its scheduled window, or use its reviewed, redacted mapped-table CSV and exact projected column types if the evidence captures equivalent reads. Save image and extension identities, read role, exact SQL, column types, mapping and the observed rows at initial copy, insert, update and delete. Record catalog snapshot attribution only when the row reads can be tied to it. If the available probe omits a required type, record that gap and coordinate a narrowly scoped follow-up trial.
2. At each hold point use `read_projections(local_psql_command, {"probe": ((schema, table), columns, pk)}, 10)` on the actual mapped table. For replayed evidence, feed the actual psql CSV envelope through the same parsing path as the psql transport tests. Apply `normalize_rows("probe", capture.rows["probe"], columns, pk, integer_columns, timestamp_columns)` and use `tests.fixture_oracle.compare_rows` against the manually declared probe rows. Capture the same check at the source independently. Use separate phase and side labels in the evidence. Verify retained deletes and duplicates by key and confirm an intentionally wrong expected value emits a keyed diff.
3. For the live follow-up, stage the tested revision using the [EXP-011 guest procedure](../../tests/integration/remote-probe/README.md#run-in-the-guest). In the staged copy, apply the experiment bundle's `runner.patch` and place `probe_parity.py` at its root. The patch gives the run an EXP-013 and ticket 2.3 identity and runs the following at each passing native hold point before the writer resumes.

   ```sh
   python3 probe_parity.py "$label" "$source_id" "$consumer_id" | tee "$evidence/$label.parity"
   ```

   This invokes the parity adapter with a 5 s client/read budget on each side. In that same read-only transaction, it sends `SELECT current_setting('transaction_read_only'), current_setting('transaction_isolation')` to psql's stderr output before the bounded row projection. It independently checks each side against the manually declared probe rows.

4. At initial copy, query `pg_attribute` with `pg_catalog.format_type(atttypid, atttypmod)` for the mapped relations and check both clients with `psql --version`. Run the target server timeout control with `psql -XwqAt -v ON_ERROR_STOP=1 -v VERBOSITY=sqlstate -f -`:

   ```sql
   BEGIN READ ONLY;
   SET LOCAL statement_timeout = '100ms';
   SELECT pg_sleep(2);
   ```

   Expect psql exit 3, SQLSTATE `57014` and implicit rollback on disconnect. At the final hold point deliberately compare target key 1 against its original value and record the resulting diff. Re-run the offline checks against current main. Ticket 2.6 owns four-table runtime validation.

## Expected results

S00–S06 produce empty diff lists on both sides. Altered rows produce phase- and side-labelled missing, duplicate, extra or unequal row differences. Overflow fails before a truncated result can be accepted. A missed target deadline preserves the latest mismatch and returns a timeout outcome. The selected build should produce the exact table types and rows recorded by ticket 2.1 within the declared read budget.

## Actual observations

The isolated parity suite passed 15 tests and the full suite passed 39. Repository checks passed, including all five deliberately failing controls. The oracle and expected JSON had zero diff from main. In the offline poll example, source and first target captures held the pre-delete state, and the second target capture matched S03. Source stayed `mismatch`, target returned `pass`, and the combined result remained failed.

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

### Selected-build replay

The checksummed EXP-011 excerpt identifies `probe.items` mapped to `bronze.items` through the `ducklake` access method. The native read returned unaligned psql text with two fields. The replay uses those source and target field values unchanged, re-framed as CSV for the adapter. It compares against probe expectations declared independently of the captured data. The source DDL declares `id integer` and `value text`. The pinned target creator introspects the source column types and preserves both type names. It adds `_duckpipe_source` outside the business projection. [Native probe](../../tests/integration/remote-probe/run.sh) · [Pinned target DDL](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/duckpipe-pg/src/api.rs#L903-L993) · [Pinned type mapping](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/duckpipe-core/src/types.rs#L645-L650)

| Hold point | Source and first passing target | Last failing target diff | Latest snapshot observed separately in EXP-011 |
| --- | --- | --- | --- |
| Initial | `(1, 'seed')` | `items: missing key id=1` | 2 |
| Insert | `(1, 'seed'), (2, 'inserted')` | `items: missing key id=2` | 3 |
| Update | `(1, 'updated'), (2, 'inserted')` | `items: unequal id=1 value: expected 'updated', got 'seed'` | 4 |
| Delete | `(1, 'updated')` | `items: extra key id=2` | 5 |

All eight passing reads produced zero differences. The four stale reads produced the differences above. Catalog observations followed the independent row reads, so the historical snapshot IDs remain contextual evidence. The replay carries no attributed snapshot ID. The selected probe covers integer and text. The v1 timestamp projection has offline UTC coverage. [EXP-011 guest observations](evidence/EXP-011-guest-observations.txt) · [Replay test](../../tests/unit/test_cdc_parity_exp011.py)

### Disconnected guest follow-up

Run `20261126T082754Z-p02-01` used the pinned EXP-011 images, a fresh two-vCPU, 2 GiB NIC-free guest overlay `guest-01.qcow2`, project `cdc23-20261126t082754z`, bridge `p23082754`, group `g23_20261126t082754z`, publication `pub23_20261126t082754z` and slot `slot23_20261126t082754z`. The existing isolated workload and limits were retained, including the 480 s overall deadline, 60 s per native checkpoint, 500 ms native polling, and 768 MiB source / 512 MiB consumer memory caps with zero swap. The source and consumer used distinct named volumes on the verified internal bridge without published ports.

Source and target psql reported 16.16 and 18.4. `pg_attribute` returned `id|integer` and `value|text` for both relations, plus `_duckpipe_source|text` on the target. The adapter projected and normalized the two business columns. It matched all eight live source and target reads against the four independent probe expectations above. Both sessions reported `on,repeatable read` at every hold point. The target timeout control returned exit 3 and `ERROR:  57014`. The deliberately wrong expected value produced `delete target intentional mismatch: items: unequal id=1 value: expected 'seed', got 'updated'`.

| Hold point | Native target first match UTC | Subsequent adapter source / target | Latest separate catalog sample |
| --- | --- | --- | --- |
| Initial | 08:28:31.727 | Pass / pass | 2 |
| Insert | 08:28:38.847 | Pass / pass | 3 |
| Update | 08:28:43.867 | Pass / pass | 4 |
| Delete | 08:28:48.874 | Pass / pass | 5 |

The four latest snapshot IDs were observed in separate catalog queries. The adapter sessions did not pin a DuckLake version, so their catalog snapshot fields were null. The inline catalog held table ID 2. The final native target checks confirmed key 2 absent and zero duplicate keys. Both services and project cleanup exited 0 with no OOM. Publisher cleanup returned `after|0|0|t|t` and the guest powered off after exporting evidence.

## Evidence artifacts

The repository retains the [parity contract](../../scripts/cdc/parity/__init__.py), [psql adapter](../../scripts/cdc/parity/psql.py) and [offline test inputs and assertions](../../tests/unit/test_cdc_parity.py). The run bundle is in ignored `artifacts/EXP-013/20261126T082754Z-p02-01/` in the ticket worktree. The redacted guest archive `evidence-01.tar.gz` has SHA-256 `99d4eb8b7554aab4f129afbe93ce42cdf0426341043e5204217f6453e56febec`. It contains the per-checkpoint `*.parity`, catalog and poll outputs, resource samples and cleanup evidence. The directory includes the staging patch and helper together with `SHA256SUMS`.

## Interpretation, limitations and follow-up

The selected build supports the adapter's ordered read-only projection and integer/text normalization for the quiescent one-table probe. The live server timeout control and offline client deadline control exercised distinct timeout mechanisms. R02 and R03 now have independent adapter observations for the one-table initial copy and committed DML. The four-table fixture, live timestamp rendering, fault cases and an attributable cross-table cutoff remain open at the Phase 2 level. In particular R13 requires a separate visibility experiment. Ticket 2.9 owns reconciliation of the shared research register. [Ticket 2.3](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/40)
