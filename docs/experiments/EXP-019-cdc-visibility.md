# EXP-019 — Characterize multi-table visibility under commit, rollback and overlap

- **Date** 2026-11-26 UTC
- **Ticket** [2.8 / #45](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/45)
- **Research questions** R02, R03, R13, R16
- **Status** Test preparation
- **Operator** Codex
- **Prerequisites** Merged 2.6 at `629d56c`, [ADR-002](../decisions/ADR-002-phase-2-local-cdc-probe.md), [EXP-017](EXP-017-cdc-baseline.md), and the [independent PR #54 review](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/54#pullrequestreview-6071741026)

## Hypotheses

1. Staged or aborted S04 keys are absent from Bronze. After source commit, the held source checkpoint converges exactly with all three S04 rows.
2. DuckPipe can publish changes from one source transaction in more than one committed DuckLake version. An ordinary reader can also appear to see the same mixed state if it combines results from different versions.
3. S05 A and B overlap at the source and A commits first. B's aborted variant ends at exact A-only. With both committed, the pinned target converges exactly to S05. The source order may or may not yield a distinct A-only target version.

## Preconditions and verified documentation

Use the [pinned EXP-017 runtime](EXP-017-cdc-baseline.md#preconditions-and-decisions) and v1/42 oracle. PostgreSQL 16.16 is the remote publisher. PostgreSQL 18.4, DuckPipe 1.0.0 at `86d5c248d80370fb2e10ddc1abd780fd94c3a52b`, pg_ducklake 0.1.0 at `20d799e673639fb0c36a3b31db413e45057a10ed`, pg_duckdb 1.1.0 and DuckDB 1.5.1 are on the approved consumer. The existing pinned Python 3.12.12 / Psycopg 3.2.13 fixture image supplies the Phase 1 schedules.

Verified on 2026-11-26. DuckLake's 0.4 API supports `AT (VERSION => …)` and exposes `current_snapshot`. In the pinned integrated source, the latter binds to `DuckLakeTransaction::Get(context, catalog).GetSnapshot()`. Unqualified scans resolve through the transaction's cached snapshot and version-qualified scans resolve through the specified version. pg_ducklake's SPI-backed metadata calls use PostgreSQL's transaction snapshot. The PostgreSQL isolation documentation specifies fixed PostgreSQL visibility in `REPEATABLE READ`; the native DuckLake result is tested separately. [DuckLake 0.4 time travel](https://ducklake.select/docs/0.4/duckdb/usage/time_travel) · [Pinned snapshot function](https://github.com/relytcloud/pg_ducklake/blob/20d799e673639fb0c36a3b31db413e45057a10ed/third_party/ducklake/src/functions/ducklake_current_snapshot.cpp) · [Pinned version resolution](https://github.com/relytcloud/pg_ducklake/blob/20d799e673639fb0c36a3b31db413e45057a10ed/third_party/ducklake/src/storage/ducklake_transaction.cpp#L2577-L2612) · [Pinned SPI metadata path](https://github.com/relytcloud/pg_ducklake/blob/20d799e673639fb0c36a3b31db413e45057a10ed/src/pgducklake_metadata_manager.cpp#L150-L173) · [PostgreSQL 18 isolation](https://www.postgresql.org/docs/18/transaction-iso.html)

## Procedure and expected results

1. Use the [reproduction commands](../../tests/integration/cdc-visibility/README.md) on a fresh, scheduled guest overlay per variant. Reuse the EXP-017 image, internal bridge preflight, credentials, four serial registrations and guarded teardown. Require exact S00–S03 on both sides, including both customer reports. Apply the 480-second trial budget, 60-second checkpoint budget and established EXP-017 resource caps.
2. In `rollback`, prove S04 is staged in the writer and its XID is in progress while a separate source reader still sees exact S03. Sample Bronze for at least 1.5 seconds at that hold. Roll back and sample exact S03 for at least 10 seconds. Verify all retained versions since the predecessor show exact S03. Commit a later disjoint update to item 101 (quantity 4, timestamp T05), require exact source and Bronze with 1,200 and 500 cents, and replay the retained versions again to check no aborted key appears even after later CDC apply.
3. In each overlap trial, hold committed S04 at the same source gate before release. Require order 30, item 301 and payment 302 absent in sampled open reads and all present on exact S04 (1,300 and 500 cents, two orders for customer 1). Poll fresh consumer-local SQL for exact convergence every 200 ms after a read. Use one DuckDB statement for the four bounded projections and `ducklake_current_snapshot` on the same attachment. Read every catalog ID from the predecessor through the quiescent head with the same explicit version on all four relations. Report live and historical observations separately.
4. In both S04 commit trials, use one legacy-style PostgreSQL read-only `REPEATABLE READ` reader from before release until a fresh reader sees exact S04, within a 12-second native crossing window. Compare native rows and surrounding engine/PG identities before and after newer data is visible in another session. If the crossing window is missed, preserve the inconclusive test and continue probing exact convergence within 60 seconds. As a control, combine the item projection from exact S04 and other projections from exact S03, retaining all input IDs.
5. Verify S05 both-open exact S04 on the source and sample no A or B changes in Bronze for at least 1.5 seconds. Commit A and hold B open for at least 2 seconds, within the existing four-second barriers. Allow old S04 or exact A-only in this window. Then either release B or trigger the existing after-A fault. Independently verify the final committed or aborted XID statuses and exact source fixture, poll exact Bronze, and hold later writes for ten seconds. Replay retained versions from S04 through each terminal state. Both terminal states have 1,600 and 500 cents, with payment 303 present only when B commits.

## Actual observations

Runtime observations are pending the scheduled disconnected guest window.

## Evidence artifacts

The integration directory contains the SQL generation, checked schedule, evidence layout and guest commands. The final report will reference the tested SHA and selected run excerpts.

## Interpretation and pending research updates

R13 stays open for a continuously advancing source cutoff. A polling run with no mixed state cannot support atomicity. The experiment tests the earliest exact, attributable snapshot at held fixture checkpoints. R02/R03 track exact copy and CDC correctness; R16 tracks inspectable source-to-Bronze evidence. The Phase 2 shared register remains owned by the gate ticket.

## Limitations and follow-up

Consumer-local embedded DuckDB reads exercise the pinned catalog and local storage. Phase 3 still needs independent attachment to the same catalog and real file-backed reads. Future work needs a way to identify a source cutoff without pausing later writes.
