# EXP-018 — Same-slot restart and bounded publisher WAL retention

- **Date** 2026-11-26 UTC
- **Ticket** [2.7 / #44](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/44)
- **Research questions** R03–R05 and R16
- **Operator** Codex
- **Base** `629d56c` on `origin/main`, with reviewed tickets 2.1–2.6. [ADR-002](../decisions/ADR-002-phase-2-local-cdc-probe.md) · [EXP-017](EXP-017-cdc-baseline.md) · [PR #54 review](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/54#pullrequestreview-6071741026)

## Hypotheses

The exact current state survives a graceful same-volume restart and catches up from the same slot. An acknowledged checkpoint survives SIGKILL and the same target can recover later committed writes. The sparse-table control tests whether separately advancing the customer mapping changes the minimum group checkpoint and publisher feedback. A slot whose required WAL falls outside the retention limit cannot restore the existing stream, so recovery requires a fresh snapshot.

## Preconditions and procedure

- Use the reviewed EXP-017 software and archives on the approved disconnected 2-vCPU, 2-GiB guest. PostgreSQL 16.16 is the source and PostgreSQL 18.4 hosts DuckPipe 1.0.0 at `86d5c248d80370fb2e10ddc1abd780fd94c3a52b`, pg_ducklake 0.1.0, pg_duckdb 1.1.0 and DuckDB 1.5.1. The runner is CPython 3.12.12 with Psycopg 3.2.13. Use the host's exclusive runtime lock and fresh projects and volumes for all three cases. [Pins and staging](../../tests/integration/cdc-baseline/README.md#stage)
- Verified documentation on 2026-11-26. PostgreSQL 16 applies the slot reserve limit at checkpoint, and the slot catalog exposes nullable retained headroom. PostgreSQL logs the rejection when an invalidated slot attempts logical decoding. Docker can stop a specific container or send SIGKILL. The pinned connector starts logical streaming from a group checkpoint and computes a minimum across per-table progress. [PostgreSQL replication settings](https://www.postgresql.org/docs/16/runtime-config-replication.html) · [Slots](https://www.postgresql.org/docs/16/view-pg-replication-slots.html) · [CHECKPOINT](https://www.postgresql.org/docs/16/sql-checkpoint.html) · [PG16.16 invalidation error](https://github.com/postgres/postgres/blob/REL_16_16/src/backend/replication/logical/logical.c#L587-L606) · [Docker SIGKILL](https://docs.docker.com/reference/cli/docker/container/kill/) · [Pinned DuckPipe resume code](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/duckpipe-core/src/service.rs#L1274-L1320) · [Pinned minimum computation](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/duckpipe-core/src/flush_coordinator.rs#L707-L737)
- Follow the [staging, commands and limits](../../tests/integration/cdc-recovery/README.md). Emit bounded exact source and Bronze comparisons separately against fixture v1/42. Both databases keep their original resource caps, the source's slot limit remains 128 MiB and allocated WAL must stay below 256 MiB. The ordinary outage permits only the stated fixture writes and less than 16 MiB retained span. The loss trial forces at most 11 segment switches with a 176 MiB span allowance and no added business-table load. It runs on its own clone.
- After exact S02, the graceful trial stops the consumer, requires its original slot inactive, runs S03/S04 using the Phase 1 runner, and starts the same container. The abrupt trial first measures feedback across no-op updates of three noncustomer tables and then a separate customer update. These transactions preserve every fixture field. It attempts to capture S03 buffered before SIGKILL and commits S04 offline. In both cases, inspect the pre-worker durable target if the group does not start automatically, then start the original group, compare exact S04, run S05 and reread independently. The retention trial permits replacement of only the retired consumer catalog and slot after recording loss and the attempted reconnect. Source rows and enrollment remain in place.
- Each run samples PostgreSQL and DuckPipe separately. Timing uses observer monotonic time and UTC. Publisher insert LSN is a post-commit upper bracket for preceding WAL with no exact transaction COMMIT/END LSN attribution. An exact target read fresh from the stopped group's catalog addresses interruption durability. An advancing slot or healthy worker establishes progress only.

## Actual observations

### Graceful outage and same-slot catch-up

Run `20261126T131003Z-r20261126t131003z65f4` in `guest-01.qcow2` tested `d957e9a5e214e786042289442b9721f1e01ba923`. Both experiment and disposal exited 0. At the exact S02 hold, the slot was active on PID 335, with restart `0/19A7370`, confirmed `0/19A7E30` and a 105,720-byte insertion-to-restart span. The same slot became inactive with null feedback after the consumer exited 0 without OOM. Independent source S03 and S04 had zero differences. The post-S04 slot stayed inactive and confirmed stayed at `0/19A7E30`. The retained span reached 107,056 bytes and observed WAL allocation stayed at 16,392 KiB. The writes and source comparisons completed in under three seconds of the outage.

The restarted consumer retained its container, image, labeled volume, system identifier, group ID, and mapping IDs. Before starting the worker, its persisted group checkpoint was still `0/19A7E30` and order-items applied LSN was `0/19C0FA0`. An independent read then returned exact S02, including item 102. The publisher logged the same slot's `START_REPLICATION` at `0/19A7E30`. A new sender PID 1087 became active and the target reached exact S04 in 5.39 s from the explicit worker start, on read 8. Item 102 was absent and order 30, item 301 and payment 302 had all expected fields. The Phase 1 S05 continuation and a fresh second S05 read matched all rows and both aggregates.

The observed requested start was earlier than the pre-fault order-items apply position. The consumer-side persisted checkpoint and table progress can diverge. This sample supports a replay opportunity while leaving individual logical messages unattributed. The confirmed position still had not moved at S05, although three relations had advanced their applied LSNs. The rank of the minimum customer position matched the EXP-017 stall.

### Sparse activity, feedback and abrupt interruption

Run `20261126T131150Z-r20261126t131150zd818` in `guest-02.qcow2` tested `d957e9a5e214e786042289442b9721f1e01ba923`. The trial and cleanup exited 0. At S02 the source insert upper bracket was `0/19C05F8`. The group and slot stayed at `0/19A7DF8` while the independent target already matched S02. The control then changed no fixture values. It updated three noncustomer keys to their current values, waited for those applied positions, and applied a separate customer touch.

| Observation | Customer apply | Orders apply | Payments apply | Items apply | Group checkpoint and publisher confirmed flush |
| --- | --- | --- | --- | --- | --- |
| After three noncustomer applies | null | `0/19C05F8` | `0/19C0690` | `0/19C0728` | `0/19A7DF8` |
| After separate customer apply and feedback | `0/19C07F0` | `0/19C05F8` | `0/19C0690` | `0/19C0728` | `0/19C05F8` |
| After recovering S04 | `0/19C07F0` | `0/1A024F0` | `0/1A02720` | `0/1A02608` | `0/19C07F0` |

The first advance covered the sampled S02 upper bracket, and an exact S02 read passed again. This controlled variation supports the minimum-per-table explanation of the stall. Moving the oldest table moved the group only as far as the next minimum. Later writes without further customer changes again left the group at the customer position. The first feedback advance did not move physical retained WAL by the same amount. The restart position remained behind confirmed flush and changed with sender lifecycle. A periodic no-op update strategy at scale or under realistic churn remains untested.

The runner committed S03 at 13:13:04.932894 UTC, the source reader matched S03, and the connector sampled one queued item change. The next target read still matched S02. SIGKILL was requested at 13:13:05.918169. The container exited 137 with `OOMKilled=false`, and the publisher slot was inactive with confirmed flush still `0/19C05F8`. After offline S04, PostgreSQL crash recovery logged an interrupted database and redo start. Before starting any DuckPipe worker, the target had exact S03, with the verified S02 update to item 101 intact and the S03-deleted item 102 absent. The buffered-but-not-durable crash boundary was missed. The last stale read and the retained S03 bound the missed window. Survival of source-acknowledged S02 and already applied S03 was demonstrated for this consumer process/container interruption.

The same container and catalog retained their identity. The persistent group retained checkpoint `0/19C05F8` and an items applied position of `0/19C0920`. The publisher then logged `START_REPLICATION` at `0/19C05F8`, before that applied position. The new worker queued two customer changes even though the customer apply LSN already survived the restart and no subsequent transaction touched customers. The pinned FULL-identity upsert path translates an update into delete and insert work, and skips already-applied streaming records by LSN only in append mode. The queue evidence therefore shows re-admission of already-applied customer work on the controlled schedule. Exact S04 on attempt 8 followed 5.57 s after explicit worker start, with no duplicate keys or lost effects. S05 subsequently passed and a fresh independent read matched. The experiment did not attribute individual wire messages, so transport-level duplication and exactly-once transport remain unverified. [Pinned update and skip paths](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/duckpipe-core/src/service.rs#L160-L178)

### Retention crossing, reconnect failure and clean resnapshot

Run `20261126T131746Z-r20261126t131746zba52` in `guest-05.qcow2` tested `0a076665254865cc47ce792b48a415bfca992698`. Both experiment and cleanup exited 0. The offline source independently matched S03 and S04. Actual settings were 16 MiB segments, 128 MiB slot retention, zero `wal_keep_size` and archive off. Generation stopped on loss at switch 9, about five seconds after the first forcing observation.

| Publisher sample | Insert-to-restart bytes | `wal_status` | `safe_wal_size` bytes | WAL allocated KiB |
| --- | ---: | --- | ---: | ---: |
| After switch 8 | 124,093,208 | reserved | 16,777,000 | 147,464 |
| After switch 9 and checkpoint | null | lost | null | 65,544 |

The slot's previous restart position was `0/19A7DC0`. The ninth post-checkpoint insert position `0/A001668` was 140,875,944 bytes past that previous restart position. PG16.16 logged invalidation and cleared the live restart position. The same group attempted normal reconnect on the same slot. Both publisher and consumer logs reported `can no longer get changes from replication slot`. Authenticated consumer SQL was healthy but an independent target read still matched old S02. The independent source read matched S04. This shows that the cap governs whether PostgreSQL keeps required WAL at checkpoints. The measured physical WAL allocation and the retained address span are separate.

After the reconnect evidence, the guarded cleanup removed the four old mappings, the invalidated slot and the old publication, then verified an empty publisher inventory. The exact old consumer container and volume were retired. The replacement used a new container, volume creation time and database system identifier. The pinned extension seeded only its default local group, with no remote conninfo, no checkpoint, no mapping and no Bronze relation. The enrolled source remained in place. The fresh group and slot reused the per-run names with a distinct publication OID and slot creation fingerprint. Publication OID changed from 16468 to 16478 and slot creation confirmed position from `0/19A6F80` to `0/A054F80`.

The first independent four-table read after serial resnapshot matched exact S04 at 13:19:18.337471 UTC, about 10.64 s after verification of the fresh consumer and 20.76 s after observed loss. Item 102 was absent. The source S04 receipt remained intact, as checked by the subsequent runner's S05 predecessor. S05 and the fresh S05 target read then matched exactly. This was recovery of current state from an authoritative source. The retired consumer's history was discarded.

Attempts 03 and 04 also reproduced WAL loss and reconnect rejection and cleaned up. They stopped during replacement on an incorrect assertion that the fresh consumer had no group whatsoever. Attempt 04 captured `1|0|0|f` for group count, mapping count, Bronze relation count and presence of the Bronze schema. The corrected assertion uses the pinned extension bootstrap inventory and requires the exact built-in default row. [Pinned bootstrap SQL](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/duckpipe-pg/src/sql/bootstrap.sql#L66-L70)

### Resource observations

The isolated amd64 guest used kernel 6.8.0-147, Docker Engine 29.1.3 with containerd, Compose 2.40.3 and cgroup v2. The measured source and consumer memory peaks were 225.5 and 183.4 MiB in the graceful trial, 224.7 and 202.7 MiB in the abrupt trial, and 343.2 and 186.4 MiB across the retention trial and resnapshot. Source PGDATA after switch 8 was 178,520 KiB, with at least 3,227,012 KiB free across the retention trial. OOM counters remained zero. The original memory, CPU, swap and disk ceilings stayed in force. The source and consumer cleanup verified clean exits and removal of replication objects and runtime assets. Ticket 2.8 was given the shared runtime lock after the last guest powered off.

## Evidence and checks

- [Guest procedures](../../tests/integration/cdc-recovery/README.md) and [checksummed observations](evidence/EXP-018-guest-observations.txt) contain commands, image identity, selected source and connector samples, scope, exact checks, log excerpts and both setup failures. Run `sha256sum -c docs/experiments/evidence/EXP-018.sha256`.
- Full redacted guest bundles are under ignored `artifacts/EXP-018/` in the dedicated worktree. Passing graceful, abrupt and retention export SHA-256 values were `f91edd2af122916ef80782b8ede5242cf5c8843d6d6cd0de8ca186e4ad4e4af1`, `aed4c78e283843e5582c08af9c65eb7b9f3d7b42511e8b2e822bda8db2da884c`, and `7fd98d590cf64b59641d1e0c495a1f23498a30f51445e8103ab15500e29f65f4`.
- `make help check BASE=origin/main`, `make test-unit` (47 tests), `sh tests/repository-checks.sh` (five controls), launcher syntax, Python compilation, and independent verification of the canonical checkpoint exports against the checked-in v1 oracle passed. The fixture oracle, shared implementations, images and Compose caps stayed unchanged.

## Interpretation and pending research updates

| Question | Evidence and remaining scope |
| --- | --- |
| R03 | Exact current-state rows and aggregates survived the tested interruption schedules and fresh resnapshot. |
| R04 | The no-op control isolates a sparse-table minimum in one controlled workload. Slot feedback, physical WAL retention and durable exact contents diverged. A mitigation for sustained sparse activity remains open. |
| R05 | Same-slot recovery passed for the tested graceful and abrupt container interruptions. The isolated loss control confirmed an unrecoverable stream and exact clean resnapshot. The buffered-but-not-durable crash window, power-loss durability and repeated or high-load recovery remain open. |
| R16 | The same experiment chain records writer commit, independent source and target rows, worker state, separate source feedback and the reconnect error. Cross-stage operator walkthroughs remain open. |

The small recoverable outage passed within its declared bounds. The sparse-table stall is a retention risk under sustained WAL growth. The clean resnapshot recovered current state after that boundary was deliberately crossed. The Phase 2 gate still needs a resolved operational retention policy and its separate visibility evidence.
