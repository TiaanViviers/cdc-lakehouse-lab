# EXP-017 — Verify four-table initial copy and ongoing CDC

- **Date:** 2026-11-26 UTC
- **Verdict:** Passed exact checkpoint convergence, sampled rollback exclusion and the controlled COPY overlap. The active slot showed a feedback stall and an ordinary Bronze read showed a mixed S04 state.
- **Ticket:** [2.6 / #43](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/43)
- **Research questions:** R01–R04, R13, R16
- **Operator:** Codex
- **Prerequisites:** Merged Phase 2 work through `9bc80fb7de70909685cbad871a3f0298dd5c50c2`. [ADR-002](../decisions/ADR-002-phase-2-local-cdc-probe.md) · [Approved ticket](../../backlog/phase-2.md#26-verify-four-table-initial-copy-and-ongoing-cdc)

## Hypotheses

The pinned remote connector will converge exactly to S00 after four serial copies, then to each committed S01–S04 checkpoint. Aborted S04 will leave every observed target read at S03. A commit on the table currently being copied will converge to its exact expected state after the copy barrier releases.

## Preconditions and decisions

- Use the merged source publisher CLI, consumer profile, Phase 1 runner, parity adapter and publisher observer. The guest uses 2 vCPUs, 2 GiB, no NIC and a fresh overlay for each trial. One guest holds the exclusive runtime lock. Each trial starts with distinct project, source cluster, consumer cluster, bridge, roles, group, publication and volumes. Hold source writes at each checkpoint until the independent read finishes.
- Use PostgreSQL 16.16 Bookworm, the pinned DuckPipe PostgreSQL 18.4 bundle, DuckPipe 1.0.0 at `86d5c248d80370fb2e10ddc1abd780fd94c3a52b`, pg_ducklake 0.1.0 at `20d799e673639fb0c36a3b31db413e45057a10ed`, pg_duckdb 1.1.0 and DuckDB 1.5.1. Reuse the Phase 1 runner artifact with CPython 3.12.12 and Psycopg 3.2.13. The runner's linux/amd64 manifest is `4943252833777c83625c654bebe643a0e4a58ff351f22fbc177810da8890b9dc`, with config `0d8274eb2dfdbdfa55d3fe9ddcd2d954a06632e0ecc348341570915ae95ffa73`.
- Verified documentation and code on 2026-11-26. The pinned DuckPipe snapshot opens a repeatable-read source transaction, creates a temporary `pgoutput` slot and runs `COPY (SELECT …) TO STDOUT`. PostgreSQL 16 documents that forced row-level security applies to a non-bypass table owner. A SELECT policy can call a transaction-scoped advisory lock without changing row values. PostgreSQL exposes backend wait events and blocking PIDs separately from the slot's received positions. [Pinned DuckPipe implementation](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/duckpipe-core/src/snapshot.rs) · [PostgreSQL 16 row security](https://www.postgresql.org/docs/16/ddl-rowsecurity.html) · [Advisory locks](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS) · [Activity and feedback](https://www.postgresql.org/docs/16/monitoring-stats.html) · [Slot fields](https://www.postgresql.org/docs/16/view-pg-replication-slots.html)
- The full checkpoint comparator reads each side in a fresh PostgreSQL read-only repeatable-read transaction and computes both customer aggregates from its four bounded tables. The oracle is the checked-in fixture v1/42 JSON. The target read proof is consumer-local SQL with query routing off. Catalog IDs are sampled separately and are unattributed to individual reads. [Fixture oracle](../../tests/fixtures/v1/expected.json) · [Parity adapter](../../scripts/cdc/parity/psql.py)

## Procedure and expected results

1. Follow the [staging and guest commands](../../tests/integration/cdc-baseline/README.md). Run `baseline` with an outer deadline of 480 seconds and up to 60 seconds for each initial copy or target checkpoint. Poll at 500 ms after a read. The unpublished source and consumer each have a single interface on the same gated internal bridge. The caps are 768 MiB / 1 CPU for the publisher, 512 MiB / 0.75 CPU for the consumer and 256 MiB / 0.5 CPU for one runner. Check zero swap and OOM counters, source WAL below 256 MiB, each named volume below 512 MiB, 64 MiB consumer tmpfs and at least 1 GiB free. PostgreSQL limits slot WAL retention to 128 MiB, evaluated at checkpoints.
2. Prove exact source S00 while publication and slot inventories are empty. Create the group and verify the empty named publication and persistent logical slot. Add customers, orders, payments and order items serially. For each table require its exact keyed seed rows, a recorded snapshot LSN, a catch-up or streaming state, and temporary slot release before the next registration. Verify four unfiltered publication members, expected operations and table privileges, and exact target S00. Source receipts and installation data stay outside the mapping.
3. Commit S01, S02 and S03 through the Phase 1 runner. The published schedule inserts item 102, updates item 101 and deletes item 102, respectively. Stage and abort S04, then require full S03 parity on every sampled read for a minimum of 10 seconds. Commit S04 and require exact source and target state including order 30, item 301 and payment 302 and totals of 1,300 and 500 cents. Record distinct source transaction, connector, slot and target-read evidence. Observe a further 10 seconds of feedback while the source is quiescent.
4. Repeat with `copy-window` on fresh volumes. Use a trial-only source SELECT policy on `fixture.order_items` that requests a shared advisory lock for the publisher. Hold the exclusive lock in a separate bounded session. Confirm a temporary-slot COPY backend is waiting on that exact session and record the same COPY identity before and after the runner commits S01. Release the barrier and require full exact S01, including one item 102. Declare a missed boundary inconclusive and retain the risk. After a successful overlap, exercise a supplemental source-writer transaction changing item 102 to quantity 4 and its fixed UTC update timestamp, followed by a delete. The independent expected update preserves every other field and expects customer 1 at 2,600 cents. The delete returns both sides to exact S00. This covers the literal item 102 update without changing the published Phase 1 runner or oracle.
5. Inspect the local catalog and storage, sample final resource use, stop the group, and confirm that the tracked publisher objects can be removed under the existing guards. Separately require clean service exits and removal of the named volumes and bridge before removing its firewall rules.

## Actual observations

### Quiescent four-table baseline

Run `20261126T093439Z-r20261126t093439z558a` on `guest-05.qcow2` tested `2ca6f23b31f6b41d10e10166affbfd182c9b8f5b`. Ubuntu 24.04.5 amd64 ran Linux 6.8.0-147, Docker Engine 29.1.3 with the containerd store, Compose 2.40.3 and cgroup v2. The empty-bridge preflight passed its IPv4/IPv6 host, LAN, VPN and DNS controls. Both services had distinct PID and network namespaces, one internal endpoint each and no published ports. The experiment and cleanup both exited 0.

- The independently normalized source S00 matched the oracle before registration. The empty source inventory became one empty allow-listed publication and one logical persistent `pgoutput` slot in `source_lab` after group creation. Exact table reads passed serially. The publisher observed `duckpipe_snap_1` and `duckpipe_snap_2` live during the first two registrations, and one persistent slot after each of the four registrations. The polls did not see the payments or order-items temporary slots live. Connector samples recorded a snapshot LSN for all four and `CATCHUP` or `STREAMING` before the next table.
- Final membership held only the four unfiltered business tables with every fixture column. The pinned connector maintained four current-state DuckLake tables. Publisher ownership was reduced to the ongoing scoped role after onboarding. Neither the source receipt nor the installation relation had a Bronze mapping.
- The aborted S04 runner recorded staged state in the writer, S03 in its separate reader before rollback, and S03 plus no S04 receipt after rollback. Eleven separate target captures matched exact S03 on their first attempt over the 10-second post-abort window. Order 30, item 301 and payment 302 remained absent at those reads.
- Committed S04 reached exact parity. Its last mismatching read included item 301, while order 30 and payment 302 were still absent. Customer 1 still had one order and 900 cents. The next read matched all three keys and both reports. This is reader-visible mixed state during convergence. The parity transaction did not identify a shared DuckLake snapshot ID for that mixed read.

| Checkpoint | First exact target UTC | Target attempts | Observer elapsed from recorded commit receipt | Exact customer 1 / customer 2 cents |
| --- | --- | ---: | ---: | --- |
| S00 | 09:35:29.477662 | 1 | 11.02 s, including serial onboarding | 600 / 500 |
| S01 | 09:35:36.169898 | 8 | 5.01 s | 1,100 / 500 |
| S02 | 09:35:41.497677 | 6 | 3.69 s | 1,400 / 500 |
| S03 | 09:35:46.264455 | 5 | 3.13 s | 900 / 500 |
| S04 | 09:36:05.572481 | 9 | 5.87 s | 1,300 / 500 |

UTC values mark the end of the first exact target read. Durations use the guest controller's monotonic clock from when it received the runner's result. The runner emits its own UTC commit acknowledgement before that receipt. The read may lag actual visibility by up to the observation cadence plus query time. The JSON trace has the separately sampled source insert/write/flush positions and runner XID. No transaction COMMIT or END LSN was attributed.

### Acknowledgement and locally stored data

The persistent slot was active with sender PID 316. Its `confirmed_flush_lsn`, restart LSN and the connector's group checkpoint stayed at `0/19A7C28` after initial copy, through S01–S04, and through the final 10-second feedback hold. The sender's `sent_lsn` reached `0/1A027E0` during the hold, with a maximum measured insert-to-restart span of 372,000 bytes. Actual WAL allocation stayed at 16,392 KiB. At exact S04, the queue drained to zero and the order, item and payment mappings reported later applied LSNs. The unchanged customer table remained `STREAMING` with its initial snapshot LSN equal to the stalled group checkpoint and a null apply LSN. The pinned upstream minimum-across-active-tables calculation is consistent with a sparse table holding feedback back. This run observed no catch-up of that acknowledgement and no lost committed fixture effects. It did not vary customer writes to isolate the cause. [Pinned flush coordinator](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/duckpipe-core/src/flush_coordinator.rs#L707-L737)

The final quiescent catalog inspection showed DuckLake 0.4, four inline tables, snapshots 0–14 and zero referenced Parquet or delete files. Peak source and consumer memory were 224.3 MiB and 188.7 MiB, respectively. The consumer recorded 51 throttled periods and 1.792 seconds throttled. The sampled named volumes reached 47,688 KiB and 41,532 KiB, and free guest space stayed over 3.2 GiB. OOM counters stayed at zero. The guarded removal verified no publisher objects remained, and the guest logged clean removal of both services, both volumes and the bridge.


### Controlled write during COPY

Run `20261126T093631Z-r20261126t093631z3adc` on the separate `guest-06.qcow2` overlay tested the same revision and exited 0 with cleanup 0. Source backend 508, linked to temporary `duckpipe_snap_4`, started the order-items COPY at 09:37:29.176444 UTC. It was observed in an advisory lock wait behind PID 488 at 09:37:29.477338. The unmodified S01 runner acknowledged source XID 756 at 09:37:30.638755. The same COPY PID, slot, query start and blocker were observed at 09:37:31.110927. The controller released the hold at 09:37:31.118934.

The connector reported two snapshot rows. The last nonmatching order-items read held only 101 and 201 and showed one queued change. Exact item keys 101, 102 and 201 appeared at 09:37:36.208376. Exact four-table S01 and both reports followed at 09:37:38.857898. In the same dataset, the supplemental update set only item 102 quantity to 4 and its update timestamp to `2026-01-01T00:07:00Z`. Its full updated row and the 2,600-cent aggregate first passed 1.45 s after the source acknowledgement. The subsequent delete returned both sides to exact S00 in 4.69 s. No duplicated key or lost fixture effect appeared in the converged state. This bounded, instrumented schedule exercises an insert on the copying relation and current-state DML. It leaves transport-level duplicate delivery and other overlap schedules open.

The slot in this trial also held its confirmed position, `0/19A7C60`, across the final feedback samples while the order-items applied LSN had advanced to `0/19CB948`. The source and consumer respectively peaked at 225.9 and 183.8 MiB with no OOM. The barrier was removed, the publisher objects were removed under their existing guards and both services stopped cleanly.

### Setup attempts

Attempts 01 and 02 stopped before bridge creation on the runner image guard. The staged ID field first lacked a matching tag, then held the image config SHA instead of the manifest SHA reported by the guest's containerd store. Attempts 03 and 04 reached the first target table and stopped at `unexpected psql projection header`. The merged consumer SQL helper defaults to tuples-only output. Enabling CSV headers only on the parity client preserved both upstream interfaces. The four attempts all recorded cleanup exit 0. Both successful trials tested the corrected client on new overlays.

## Evidence artifacts

- [Reproduce the guest runs](../../tests/integration/cdc-baseline/README.md). The source and probe transfers match the hashes from [EXP-011](EXP-011-remote-pg16-probe.md#image-provenance). The consumer transfer matches [EXP-015](EXP-015-consumer-local-sink.md#image-staging). Runner archive SHA-256 was `d5a18de489abd06fdfdc0e464898d182ea9d48c519a84ec01e8500a62977fc99`. The staged checkout archive was `2aa2e76171cb0608534c3b159494e6869418000ebb93f203843d32f5387e7a86`.
- The [guest excerpts](evidence/EXP-017-guest-observations.txt) retain run identities, selected WAL and connector samples, exact rows and diffs, rollback reads, COPY evidence, catalog and resource observations. Verify them with `sha256sum -c docs/experiments/evidence/EXP-017.sha256`. The ignored `artifacts/EXP-017/` directory in the dedicated worktree holds the full guest captures. Exported baseline and overlap archive SHA-256 were `8c50cf5b21845e447fdb235ae1aedb6be2313a9f27e3ee0f0bb3c8b47a88aba1` and `cf70b870d46ac6ad9f8bf578cb01030ef97967f7972a1fd6b5fc071f969dfc2b`, respectively.
- `make help check BASE=origin/main`, `make test-unit` (47 tests), `sh tests/repository-checks.sh` (five controls), Bash syntax and Python compilation passed. A Git diff verified the shared implementations, fixture oracle and expected v1 JSON were untouched. The two isolated guest experiments and their cleanup checks passed.

## Interpretation and pending Phase 2 research updates

| Question | EXP-017 result and remaining scope |
| --- | --- |
| R01–R03 | The pinned remote runtime maintained exact four-table local Bronze after serial initial copy and at held fixture checkpoints. The controlled copy overlap preserved exact S01. The explicit item 102 update and delete converged. |
| R04 | PostgreSQL slot feedback, connector checkpoint and applied positions, and independent data visibility were separately observed. A sparse-table acknowledgement stall is a plausible explanation for observed feedback. Recovery and sustained WAL retention remain open for 2.7. |
| R13 | A direct read saw partial S04 during apply. Later quiescent parity passed. A reproducible shared-version cutoff and systematic S04/S05 visibility are assigned to 2.8. |
| R16 | A redacted trace ties source transaction events, connector telemetry and WAL feedback to independent value checks. Cross-stage and reviewer timing remain open. |

The 2.6 convergence and overlap proof passes for the tested fixture. The acknowledgement stall and mixed S04 read constrain the Phase 2 gate. Exact current-state convergence under held writes establishes a usable read boundary for this run. Restart durability, prolonged WAL growth and multi-table atomicity each require their assigned experiments.
