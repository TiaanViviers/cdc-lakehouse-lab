# EXP-019 — Characterize multi-table visibility under commit, rollback and overlap

- **Date** 2026-11-26 UTC
- **Ticket** [2.8 / #45](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/45)
- **Research questions** R02, R03, R13, R16
- **Status** All three isolated schedules passed. Two retained partial versions disproved atomic source-to-Bronze visibility on this build.
- **Runtime revision** `c8a56192187dea1eb3bdc2dc3423780ecfee678c`
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

The guests used Linux 6.8.0-147, Docker Engine 29.1.3 with the containerd store and Compose 2.40.3. The no-NIC check and the existing bridge isolation probes passed before each run. The consumer reported catalog format 0.4 with four inline tables and no referenced data or delete files. The largest measured memory peaks over the successful runs were 224.9 MiB for the source and 215.7 MiB for the consumer. Source WAL allocation reached 16,392 KiB. The sampled free space stayed above 3.2 GiB and OOM counters stayed at zero. The persistent slot's confirmed position and the group checkpoint stayed fixed after initial copy while exact S04 and S05 effects became visible. All three passing trials verified guarded removal of the publisher objects, stopped both database containers cleanly and removed their volumes and bridge.

Live sampling waited 200 ms after each query. In the successful both-commit trial, S04 convergence reads started 321–470 ms apart including query and client overhead. There was also a gap between source acknowledgement and the first fresh query while the runner returned its checks. Retained-version reads covered the saved states missed between polls. Every read retains its own timing bounds.

### S04 rollback

Run `20261126T132010Z-r20261126t132010zc046` on `guest-01.qcow2` exited 0 with cleanup 0. S04 XID 754 staged all three rows and its receipt in the source writer. The separate source backend recorded exact S03 and `in progress`. Six fresh Bronze reads over 1.79 seconds and the held native PostgreSQL reader saw exact S03 at DuckLake version 11. Source rollback acknowledged at 13:21:20.546641 UTC. Thirty fresh reads over the next 10.01-second sampling window and a fresh native read remained exact S03. The retained range contained only version 11.

The later disjoint item 101 commit produced exact `S03-control` at version 12. A fresh, pinned read at 12 and a reread of 11 both excluded order 30, item 301 and payment 302. Version 12 matched the full updated item row and both reports at 1,200 and 500 cents. This check exercises the rollback exclusion after verified subsequent apply.

### S04 commit and the EXP-017 counterexample

The first commit attempt proved two genuine partial catalog states. At version 12, a single statement read item 301 with neither order 30 nor payment 302. Retrospective reads with `AT (VERSION => 12)` on all four relations reproduced the same state. Version 13 added order 30 and the report already reached 1,300 cents for customer 1, although payment 302 was still absent. Version 14 was the first exact S04 version. The attempt later stopped at a publisher disk telemetry read, after these observations and before S05. See setup and retry notes below.

The successful both-commit run reproduced version 12 in 14 live reads and reproduced both partial versions in pinned reads. Live polling skipped version 13 in this run. The catalog timestamps for 13 and 14 were 61 ms apart. That interval measures the difference between recorded catalog timestamps rather than a directly measured wall-clock visibility window. Across all versions, the unchanged second customer had one order and 500 cents.

| DuckLake version | Order 30 | Item 301 | Payment 302 | Customer 1 orders / cents | Exact checkpoint |
| --- | --- | --- | --- | --- | --- |
| 11 | absent | absent | absent | 1 / 900 | S03 |
| 12 | absent | present | absent | 1 / 900 | Partial S04 |
| 13 | present | present | absent | 2 / 1,300 | Partial S04 |
| 14 | present | present | present | 2 / 1,300 | S04 |

The deliberate cross-version control produced the same item-first rows by reading items at version 14 and the other relations at 11. Its recorded per-relation IDs identify a reader composition. EXP-017's original capture has no attributable ID. EXP-019 independently demonstrates that the same symptom exists inside a single committed DuckLake version on this build.

### Reader snapshot boundaries

The native PostgreSQL reader reused a single backend in a read-only `REPEATABLE READ` transaction. Its PostgreSQL snapshot and all four bracketing engine identity calls stayed at the original view, with DuckLake ID 11. The exact native rows stayed at S03 after a concurrent fresh reader saw version 14 and exact S04. A new native transaction then also saw exact S04, bracketed by engine ID 14. This controlled crossing supports a shared catalog view for that native path on the pinned build. The ordinary native scans expose no individual DuckLake IDs. The embedded single-statement and explicit time-travel reads give attributable IDs across all four relations.

### S05 ordered overlap with both commits

Run `20261126T132540Z-r20261126t132540ze2cf` on `guest-04.qcow2` exited 0 with cleanup 0. A (XID 766) and B (767) were in progress on distinct source backends at the both-open barrier. The independent source reader and six Bronze reads over 1.77 seconds matched S04. A acknowledged commit at 13:27:06.398538 UTC. The source reader verified exact A-only while B was in progress. Seven Bronze reads over 2.27 seconds at that gate showed four exact S04 results and three exact A-only results at version 15.

B acknowledged commit at 13:27:08.680306 UTC. The first fresh exact S05 read ended at 13:27:09.275443 UTC on version 16, about 0.60 seconds after B's acknowledgement. Twenty-nine post-convergence reads over 10.01 seconds and a fresh native transaction stayed exact S05. The retained sequence was 14/S04, 15/A-only, 16/S05. Pinning 14 after S05 still reproduced S04. A-only and S05 each showed 1,600 and 500 cents. Payment 303 appeared first at 16. No B-only version appeared in the retained range or sampled reads for this schedule.

### S05 ordered overlap with B aborted

Run `20261126T132736Z-r20261126t132736z3c15` on `guest-03.qcow2` exited 0 with cleanup 0. The committed S04 part independently reproduced the retained 11–14 sequence and reached exact version 14 after 5.78 seconds. Six target reads over the S05 both-open hold stayed at S04. A (XID 766) committed at 13:29:09.644061 UTC. During the 2.25-second A-committed/B-open hold, one target read still showed S04 and six showed exact A-only at version 15. Its first observed A-only read was before the fault.

The Phase 1 after-A fault unwound B (XID 767). The independent source reader recorded A committed, B aborted, exact A-only and the unchanged S04 receipt. The schedule returned its expected exit 1. The first fresh post-fault target read, all thirty reads over the 10.08-second final window and a fresh native reader matched A-only. The full retained range was 14/S04 and 15/A-only. Payment 303 was absent and both report rows were exact.

## Evidence artifacts

The [integration directory](../../tests/integration/cdc-visibility/README.md) contains the SQL generation, checked schedules and guest commands. The [selected guest excerpts](evidence/EXP-019-guest-observations.txt) retain the run identities, artifact checksums, source barriers, target read timings, full versioned row values, WAL and worker samples and resource observations. Verify the excerpts with `sha256sum -c docs/experiments/evidence/EXP-019.sha256`. Full guest traces and the failed trial are preserved in the dedicated worktree under ignored `artifacts/EXP-019/`.

The first rollback trial finished with experiment and cleanup exit 0. The host serial export initially referred to the EXP-017 output path. The saved EXP-019 files were recovered by rebooting the same disconnected overlay for read-only export, with no Docker restart or rerun. Attempt `20261126T132332Z-r20261126t132332z1f62` on `guest-02.qcow2` finished S04 data and snapshot checks, then failed closed on the shared publisher observer's `disk_capture` guard. SQL slot telemetry succeeded and the disk sample was unavailable. The exact disk subcommand failure was unavailable in the redacted observer output. Cleanup exited 0. The same runtime revision passed on the fresh `guest-04.qcow2` overlay, including its disk checks.

Offline checks passed with `make help check BASE=origin/main`, `make test-unit` (47 tests), `sh tests/repository-checks.sh` (five controls), Bash syntax, Python compilation, and a synthetic smoke check for requested-version validation, native result parsing, the split-version signature and independent report values. The runtime files and dependencies in the tested commit are unchanged in the final branch.

## Interpretation and pending research updates

**Observed consistency contract.** A shared DuckLake version gives a coherent view of the lake. That version can carry only part of one committed source transaction. S04 versions 12 and 13 disprove atomic source-to-Bronze visibility on the pinned Phase 2 path. S05 demonstrates source order and eventual exact effects for the two tested schedules.

**Earliest demonstrated safe read boundary.** Hold later source writes at the intended checkpoint, independently confirm the exact committed source fixture, and use one explicitly named Bronze version whose four full business projections and both reports match it. Version 14 was the first such S04 snapshot. In the successful both-commit run the first fresh exact read ended at 13:27:01.939786 UTC, 6.27 seconds after S04's source acknowledgement. Version 15 was the first exact A-only view while B was still open and was verified as the terminal view after B aborted in the separate trial. Version 16 was the first exact S05 view after both commits. A downstream reader can pin these tested versions, including an earlier one after newer data appears. Snapshot times, source commit acknowledgement, aggregate parity alone, slot feedback and queue depth are insufficient substitutes for verified full parity. The measured delays are specific to these runs.

| Question | Pending Phase 2 register update |
| --- | --- |
| R02 | Four serial copies gave exact S00 before each visibility trial. |
| R03 | S04 converged exactly after commit and stayed excluded after abort, including after a later applied update. S05 reached exact A-only and exact both-commit terminal states under the respective schedules. |
| R13 | Keep **OPEN**. The held fixture cutoff is demonstrated locally. A cutoff for a continuously advancing source remains unverified. The partial versions are counterexamples to atomic visibility. |
| R16 | Source XIDs, barriers, publisher/worker samples and named reader snapshots make the source-to-Bronze path inspectable. A timed reviewer walkthrough and downstream stages remain open. |

## Limitations and follow-up

Consumer-local embedded DuckDB reads exercise the pinned catalog and local storage. Phase 3 still needs independent attachment to the same catalog and real file-backed reads. Future work needs a way to identify a source cutoff without pausing later writes.
