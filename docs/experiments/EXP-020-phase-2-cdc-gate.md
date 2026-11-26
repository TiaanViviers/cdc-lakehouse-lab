# EXP-020 — Verify the complete Phase 2 CDC gate

- **Date** 2026-11-26 UTC
- **Verdict** M2 unmet. Sustained sparse-table WAL growth was reproduced while exact held checkpoints continued. Three separate COPY-overlap runs missed the same committed insert at their deadlines.
- **Ticket** [2.9 / #46](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/46)
- **Research questions** R01–R06, R08, R09, R13, R16
- **Operator** Codex
- **Base** `2cc8f90` on `origin/main`, with 2.1–2.8 merged. [ADR-002](../decisions/ADR-002-phase-2-local-cdc-probe.md) · [Approved Phase 2 gate](../../backlog/phase-2.md#29-verify-the-complete-phase-2-cdc-gate) · [Verification protocol](../verification-plan.md)

## Hypothesis and decision criteria

The pinned remote runtime will match the independent fixture at S00–S05, exclude uncommitted effects and deleted rows, and preserve exact data through same-slot restart and consumer replacement. The publisher's retention headroom must remain operationally bounded during ordinary and sparse activity. Both fresh runs must pass scoped access, isolation, measured resource, lifecycle and repeatability checks. A short sequence of exact matches can coexist with unsafe retention.

Commit-atomic Bronze visibility, an exact crash before pending work becomes durable, continuous-source scheduling, independent process attachment, and downstream storage validation have distinct experimental scopes. Partial Bronze versions inform R13 and the operator read boundary. Deliberate WAL invalidation tests failure and resnapshot behavior. It cannot satisfy the normal retention requirement.

## Preconditions and verified documentation

- Use the stock PostgreSQL 16.16 Bookworm publisher and the PG18.4 consumer bundle with DuckPipe 1.0.0 at `86d5c248d80370fb2e10ddc1abd780fd94c3a52b`, pg_ducklake 0.1.0 at `20d799e673639fb0c36a3b31db413e45057a10ed`, pg_duckdb 1.1.0, and DuckDB 1.5.1. The fixture image runs CPython 3.12.12 and Psycopg 3.2.13. The independently maintained v1 / seed 42 oracle and consumer-local PostgreSQL reads verify all fixture columns and both customer reports. The consumer uses local DuckLake tables with query routing off. [Pin provenance](EXP-011-remote-pg16-probe.md#image-provenance) · [Fixture oracle](../../tests/fixtures/v1/expected.json)
- A no-NIC QEMU/KVM guest uses two vCPUs and 2 GiB, one reserved runtime slot, and read-only staged media. Each acceptance stack has a distinct project, guarded internal dual-stack bridge, PostgreSQL clusters, named data volumes, publication, group and logical slot. Initial and ongoing source checks run on stock PG16. The consumer reads its own PostgreSQL catalog and local lake path.
- Verified on 2026-11-26. PostgreSQL 16 exposes the confirmed receipt LSN, restart LSN and estimated safe WAL size separately. PostgreSQL evaluates the slot retention cap at checkpoints. Logical streaming can resume at the later of the requested position and the slot's confirmed position. Versions, SQL result visibility and transport positions use different clocks and semantics. [PG16 slot fields](https://www.postgresql.org/docs/16/view-pg-replication-slots.html) · [PG16 retention settings](https://www.postgresql.org/docs/16/runtime-config-replication.html) · [PG16 streaming protocol](https://www.postgresql.org/docs/16/protocol-replication.html)
- The pinned DuckPipe source computes the group position as a minimum over participating tables, which is consistent with the sparse-table controls. The selected DuckLake code resolves explicit versions through the versioned transaction path. The bundled pg_ducklake exposes a scoped inline flush. Compose 2.40.3 supports explicit recreation preserving mounted named volumes. [Pinned DuckPipe coordinator](https://github.com/relytcloud/pg_duckpipe/blob/86d5c248d80370fb2e10ddc1abd780fd94c3a52b/duckpipe-core/src/flush_coordinator.rs#L658-L698) · [Pinned version resolution](https://github.com/relytcloud/pg_ducklake/blob/20d799e673639fb0c36a3b31db413e45057a10ed/third_party/ducklake/src/storage/ducklake_transaction.cpp#L2577-L2612) · [Pinned flush API](https://github.com/relytcloud/pg_ducklake/blob/20d799e673639fb0c36a3b31db413e45057a10ed/sql/pg_ducklake--0.1.0.sql) · [Compose up](https://docs.docker.com/reference/cli/docker/compose/up/)

## Procedure and expected results

1. Follow the [offline staging and reproduction procedure](../cdc-gate.md). Run `make test-cdc MEDIA=/mnt/exp020`. The two projects run serially in one reserved guest. The second starts only after checked teardown of the first.
2. Reuse EXP-017's scoped setup, serial initial copy and held independent checkpoint comparisons. Require S00, S01 insert of item 102, S02 update of item 101, and exact S03 after item 102 is deleted during a bounded graceful outage. Confirm the same container, persistent slot, cluster, group and mapping identities. Verify durable S02 before restarting the worker and exact S03 after catch-up.
3. Reuse the post-rollback wait and retained-version reads to verify S04 exclusion. Commit S04 at the source hold, check the exact named Bronze version, and record the read-only publisher-to-target walkthrough. Replace the consumer container preserving volume, PostgreSQL cluster, catalog and inactive slot. Require exact persisted S04 before worker start. Rerun the peer authentication checks and verify host gateway access remains blocked. Start the same group and require the ordered S05 overlap and exact terminal read. The established S05 B-abort and COPY hold suites exercise the other schedules on separate disposable projects.
4. Hold fixture values at S05 during three active segment-switch/checkpoint epochs. In each epoch commit a no-op update to one key in each of orders, items and payments while leaving customers idle. Require all three apply positions and drained queues, with the same active publisher sender. Compare retained address span, actual disk and safe WAL headroom after each epoch. Stop below the declared stress bound. A sustained decline in safe headroom with rising retained span fails the gate, even if exact rows survive.
5. Stop the worker and check the inline catalog, then use the documented table-scoped flush on connector-written items. Inspect verified physical references and re-read exact S05 before cleanup. Verify zero publisher slots, publications and scoped roles, with all four fixture owners and DEFAULT identities restored. Require identical canonical hashes across both source/target pairs and verify container, volume, bridge and firewall disposal before accepting the evidence.
6. Run `make help check BASE=origin/main`, `make test-unit`, `sh tests/repository-checks.sh`, Bash syntax and Python compilation. Run the existing [source-only gate](../source-gate.md) with `make test-integration` on a separate empty, enrolled PG16 project. Use the merged auxiliary experiments for the controlled COPY, abrupt interruption, full retention loss, S04 rollback, S05 B abort, and the one-table consumer auth and physical persistence checks.

## Paired integrated result

Both projects ran in `guest-24.qcow2` from `bea68d901cf18f2c740570250a0b4fda887bc98f` on merged base `2cc8f90829ae1e45992269c05d406eec178e2643`. The read-only checkout archive SHA-256 was `8f4fadd0e7c19c22ed5426a4ecbebdeb8ebe2bc29de24ac84fe025ff892646e0`. The Linux 6.8.0-147 guest ran Docker Engine 29.1.3 with the containerd store, Compose 2.40.3, cgroup v2 and Python 3.12.3. Both per-project experiments returned 0 with cleanup 0. After both teardowns, that revision’s verifier printed `M2 unmet` and returned 1, which GNU Make surfaced as exit 2. These are historical outputs. The review follow-up below gives the current command contract.

| Run order | Guest run ID | Exact source and Bronze | SQL and runtime teardown |
| --- | --- | --- | --- |
| First | `20261126T135937Z-r20261126t135937zed05` | S00–S05 and post-stress S05 | 0 slots, 0 publications, 0 scoped roles, 4 restored fixture tables. Both containers and volumes, bridge and rules removed. |
| After verified teardown | `20261126T140207Z-r20261126t140207ze431` | S00–S05 and post-stress S05 | 0 slots, 0 publications, 0 scoped roles, 4 restored fixture tables. Both containers and volumes, bridge and rules removed. |

Canonical SHA-256 matches the independent fixture on each side at every checkpoint, with identical hashes across both projects. The tables and both report rows are included in each hash. The checkpoint reports for customer 1 were 600, 1,100, 1,400, 900, 1,300 and 1,600 cents. Customer 2 stayed at 500 cents. The keyed exports preserve both sides separately.

| Checkpoint | Stable SHA-256 |
| --- | --- |
| S00 | `4a5657f9a0f7d94ef47b07ebda9966e758800ec52ac8d640215d536a439842a3` |
| S01 | `fd0b47aa24cbc35fe37b1587c2809ba259e6f70e30fb6413a4d8427432dbcaf7` |
| S02 | `98e476e4cbe28e5f95ffcdf45a0c4342b9b69ea16a8a842de9cf03a1c91f459d` |
| S03 | `9d96c16bc09199fe08540c0f62b21074bfee4c9e5ac1b3489adebb46fa032be1` |
| S04 | `379bbe49913ec661a8057e1acbf7dab420dab6d98911f20672641793cb6814cc` |
| S05 | `7450c323c202bcaf593a1a282091c0a40ef700219a272d5810d722e40582a277` |

### Recovery, access and reader observations

Graceful recovery preserved exact S02 before starting the existing worker again. The source committed the S03 delete while the original slot was inactive. Both sides then showed exact S03 and item 102 absent. The offline insert-to-restart spans were 100,560 and 100,504 bytes. Force recreation changed the consumer container ID and preserved the volume, cluster, catalog, group, mapping identities and inactive slot. A direct target read before restarting the worker returned exact S04. A fresh connection from the publisher to the replacement required SCRAM. Both TCP principals rejected incorrect passwords, and the publisher rejected the scoped role in the wrong database. Both positive guest gateway listeners timed out from the replacement consumer. The publisher's scoped role, publication and slot cleanup passed in both runs.

The S04 walkthrough returned `30|1|paid`, `301|30|2` and `302|30|400`, with read-only mode enabled, item 102 absent and identical keyed rows on both servers. Each run kept the S04 abort range at exact S03. Both runs reproduced partial S04 at versions 12 and 13 before exact S04 at version 14. Each run captured six S05 both-open reads and seven A-committed/B-open reads. The first exact both-commit S05 version was 18 in both runs. The source hold and exact keyed comparisons identify the cutoff when version numbers differ between schedules.

### Active retention and resource measurements

- First run slot confirmed flush stayed at `0/19A7DF8` and restart at `0/19A7DC0`. The final sender sent LSN was `0/40000D8`.
- Repeat run slot confirmed flush stayed at `0/19A7DF8` and restart at `0/19A7DF8`. The final sender sent LSN was `0/40000D8`.

| Epoch | First span bytes | Repeat span bytes | First safe WAL bytes | Repeat safe WAL bytes | Allocated WAL KiB, first / repeat |
| --- | ---: | ---: | ---: | ---: | ---: |
| Before test | 372,336 | 372,280 | 140,497,872 | 140,497,872 | 16,392 / 16,392 |
| First switch | 6,652,696 | 6,652,696 | 134,217,512 | 134,217,456 | 32,776 / 32,776 |
| Second switch | 23,430,808 | 23,430,752 | 117,439,400 | 117,439,400 | 49,160 / 49,160 |
| Third switch | 40,207,128 | 40,207,072 | 100,663,080 | 100,663,080 | 65,544 / 65,544 |

In both runs the sender remained active and all three updated mappings advanced while the customer mapping stayed at its initial floor. The group and slot confirmed LSNs remained pinned. All three measured epochs consumed retention headroom. The three-segment test accelerates WAL address consumption and stops within the operational safety caps. Its timing is specific to this control.

| Measure | Declared limit | First run | Repeat run |
| --- | --- | ---: | ---: |
| Publisher cgroup memory peak, MiB | 768 | 241.1 | 153.7 |
| Consumer cgroup memory peak, MiB | 512 | 196.6 | 105.2 |
| Runner cgroup memory peak, MiB | 256 | 26.7 | 25.1 |
| Publisher sampled volume, KiB | <524,288 | 96,880 | 96,876 |
| Consumer sampled volume, KiB | <524,288 | 41,516 | 41,516 |
| Minimum sampled guest free, KiB | ≥1,048,576 | 3,307,204 | 3,305,896 |
| Consumer sampled scratch, KiB | ≤65,536 | 0 | 0 |

The publisher retained the 1-CPU quota. Largest sampled cumulative CPU usage was 12.49 and 12.84 seconds per sampled cgroup incarnation, with 0.004 and 0.009 seconds throttled.
The consumer retained the 0.75-CPU quota. Largest sampled cumulative CPU usage was 14.04 and 14.21 seconds per sampled cgroup incarnation, with 2.181 and 2.628 seconds throttled.
Both consumers reported query routing off, one DuckDB thread, a `96MB` DuckDB memory setting and a `48MiB` temporary directory bound. The database cgroups retained their 128-PID limit and zero swap. The runner retained its 0.5-CPU and zero-swap limits. All sampled OOM counters were zero.

### Local catalog and physical representation

- First run had 4 inline table records and zero referenced data or delete files under the ordinary workload. The scoped order-items flush yielded one checked Parquet data reference with 11 records (2,208 bytes) and one checked Parquet delete reference with 8 positions (1,229 bytes).
- Repeat run had 4 inline table records and zero referenced data or delete files under the ordinary workload. The scoped order-items flush yielded one checked Parquet data reference with 11 records (2,208 bytes) and one checked Parquet delete reference with 8 positions (1,229 bytes).

The catalog reports format 0.4 and stores the local files under its verified named volume. The file adapter verified physical size, both PAR1 markers and SHA-256 for each reference. With its worker stopped, the live file-backed read remained exact S05 and an explicit retained version read remained exact S04. Both include the deleted-key exclusion on the logical table. Physical records and delete positions describe the representation separately.

## Decision

**M2 is unmet.** With the consumer active, the unchanged customer position held back publisher feedback as WAL accumulated over three controlled checkpoint epochs. Noncustomer table apply began from prior measured positions and crossed each epoch's bracket. Returned source and Bronze rows still matched all independent expectations. The tested short outage remained inside retained WAL. Three additional COPY-overlap trials independently missed the committed S01 insert at the deadline, making concurrent onboarding a second blocker. The separate loss control shows what happens after exhausting that headroom: the old slot cannot resume and a fresh snapshot is required.

The required correction is a reviewed connector fix or operating strategy that keeps feedback and retention bounded during sparse activity while preserving committed effects. Verify it on a pinned build with the same paired gate, a measured sparse-workload budget, alert and stop thresholds, same-slot interruption tests and a documented resnapshot procedure for lost WAL. Confirm no feedback step advances past a committed effect that can disappear across a restart. Investigate the missed COPY-overlap insert with source transaction and change LSN attribution, the COPY snapshot and consistent point, and the worker’s registration and routing decisions. Repeated controlled COPY overlap must converge exactly without a reseed. A change of connector or guarantees requires separate review. Candidate mitigations remain unverified.

### Review follow-up on the executable contract

The original verifier could emit a positive M2 verdict after the two held-checkpoint runs passed, even with the separately reproduced COPY-overlap failure. The command now emits only a paired subgate result and always requires a full M2 review. The [runbook](../cdc-gate.md#review-the-full-m2-decision) requires explicit positive COPY evidence alongside the pair and the other mandatory operational and correctness outcomes. The recorded M2 decision above includes both blockers. Historical guest exports retain their original output. [Independent PR review](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/57#pullrequestreview-6079173591)

## Consolidated Phase 2 observations

### Feedback, apply and interruption

EXP-017 observed a persistent confirmed/restart position at `0/19A7C28` through four-table S04 while the sender and three table apply positions advanced, the queue drained and independent reads converged. The customer mapping still had its original snapshot position and no apply LSN. Physical WAL in this short trial stayed at 16,392 KiB. EXP-018 controlled for sparse activity by first touching the three other tables without changing values, then issuing a separate customer touch. That raised the minimum only to the next slowest table, then later activity pinned the group at the customer's new position. Confirmed flush reflects receipt of feedback, the group reflects consumer resume progress, per-table LSNs describe apply progress, and exact keyed reads establish visibility. Disk allocation and the restart address span must both be measured. [EXP-017](EXP-017-cdc-baseline.md#acknowledgement-and-locally-stored-data) · [EXP-018 sparse control](EXP-018-cdc-recovery.md#sparse-activity-feedback-and-abrupt-interruption)

EXP-018's graceful trial preserved exact S02 before restarting the worker, caught up to S04 and continued through S05 using the original slot. In the SIGKILL trial the last pre-kill sample showed buffered S03 and exact old S02, but pre-worker recovery already showed exact S03. It proves survival of earlier acknowledged and applied state on consumer process interruption, with the buffered-but-not-durable instant missed. Start positions earlier than the per-table apply LSN and re-admitted customer work show replay exposure. The converged keyed states remained exact. Wire-level duplicates, exactly-once delivery, host or publisher power loss and sustained-load recovery remain unverified. [EXP-018 recovery](EXP-018-cdc-recovery.md#graceful-outage-and-same-slot-catch-up)

In a separate stopped-consumer clone, the ninth forced switch/checkpoint crossed the slot retention window. The old slot became `lost`, reconnect failed, and a healthy consumer SQL endpoint still returned stale S02 with source already at S04. Exact S04 after guarded retirement and clean resnapshot, followed by S05, recovered current state. The old consumer history was discarded. The configured 128 MiB protects against indefinite retention by allowing invalidation. It offers no guarantee of same-slot recovery after the required WAL is gone. [EXP-018 retention-loss experiment](EXP-018-cdc-recovery.md#retention-crossing-reconnect-failure-and-clean-resnapshot)

### Multi-table visibility and safe reads

EXP-017's mixed S04 observation lacked an attributable catalog version. EXP-019 proved two partial committed DuckLake versions with one explicit version across every projection. Version 12 contained item 301 without order 30 or payment 302. Version 13 added order 30 and produced the correct customer report total while payment 302 was still missing. Exact S04 first appeared at 14. The native repeatable-read crossing held the old catalog view on the tested path. It cannot make a partial committed version source-atomic. S05 independently demonstrated ordered A-only and both-commit views, and exact A-only with payment 303 absent after B abort, for the tested schedules. Rollback S04 also stayed absent from retained snapshots after the later disjoint commit. [EXP-019](EXP-019-cdc-visibility.md#actual-observations)

The earliest demonstrated safe read is the first explicit DuckLake version whose four full projections and both reports match an independently verified held source checkpoint. On the EXP-019 schedule this was 14 for S04, 15 for A-only and 16 for both-commit S05. A reader can pin that verified version while retained. Polling cadence, partial publication and replay limit any inference from timings or status alone. A continuous-source cutoff remains open.

### DuckLake format and files

The local PostgreSQL catalog reports DuckLake format 0.4, distinct from the pg_ducklake SQL extension release 0.1.0. The small four-table workloads use inlining under the tested settings. The pinned flush writes data records and snapshot-qualified delete positions, so physical record counts can exceed the live row count. Snapshot IDs and exact reads remain meaningful when the catalog lists zero live Parquet or delete files. The quiescent EXP-015 per-table flush materialized a checked Parquet file from DuckPipe-written data and survived volume-preserving container replacement with the worker stopped. These observations support local catalog and data persistence. Shared remote catalogs, external process attachment and S3 validation remain open. [Pinned inlined flush](https://github.com/relytcloud/pg_ducklake/blob/20d799e673639fb0c36a3b31db413e45057a10ed/third_party/ducklake/src/functions/ducklake_flush_inlined_data.cpp#L128-L182) · [EXP-015](EXP-015-consumer-local-sink.md#guest-runs) · [EXP-019](EXP-019-cdc-visibility.md#preconditions-and-verified-documentation)

## Artifact identities and review inputs

| linux/amd64 artifact | Registry index or selected manifest SHA-256 | Staged archive SHA-256 |
| --- | --- | --- |
| PostgreSQL 16.16 Bookworm | `cd0e9518bda5f2ea667ff84d22795d089720c883f288e215d97ce57437e8ef37` | `0c0a5c57fdf877a81f0930f105bb789f01d4f333e40d025584197fcdc5975366` |
| May DuckPipe PG18.4 | `091236d2acecfec1216817aff6e43dc4c036159cebe44a19c73c95c1fe9be348` | `91185421b787b82476b65f32abb02f3ae15ae01956214b4b5a12fea87a2fa38c` |
| Phase 1 runner `v1-1.8` | `4943252833777c83625c654bebe643a0e4a58ff351f22fbc177810da8890b9dc` (manifest) | `d5a18de489abd06fdfdc0e464898d182ea9d48c519a84ec01e8500a62977fc99` |
| Isolation probe `postgres-meta:v0.96.6` | Reviewed staging pin and startup allowlist | `a5ad58ea45e9e1728b51a72bc2e0bc3e2a33ca4316566faec9932cb0b5f26a13` |

The PG16 amd64 manifest and config were `d755a91aff87574a57060f86ecc0d55f83ccb51ceec6ec6f904c1210d018d998` and `76500a7555b1f245546af93974bb208366013cf537fa3038f0bdd493efe0c612`. The consumer amd64 manifest and config were `de0a9036fd11a75eaff23508209c2cea675d081aecea51f60cdca78c0802a5a6` and `a0452c3a54190ba6eeaf94dd3e434f97fd3862944c73b3f681f85eb8e3b2f56e`. The runner config was `0d8274eb2dfdbdfa55d3fe9ddcd2d954a06632e0ecc348341570915ae95ffa73`. The guest checked media SHA-256 and loaded image identity. The consumer check also verified the selected archive manifest, config and blob hashes. [Source and probe provenance](EXP-011-remote-pg16-probe.md#image-provenance) · [Consumer provenance](EXP-015-consumer-local-sink.md#image-staging) · [Pinned isolation allowlist](../../scripts/isolation/preflight.py)

The independent reviews of PRs #48–56 established prerequisite scope. The publisher evidence bundle and consumer fail-closed teardown were re-reviewed after their respective findings. The reviews of #54–56 explicitly carried the stalled feedback, missed crash boundary and partial snapshots forward to #46. The merged fixture, independent parity adapter, WAL observer, publisher guards and image pins were reused. [Publication](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/48) · [Remote probe](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/49) · [Observer](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/50) · [Parity](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/51) · [Publisher lifecycle](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/52) · [Consumer](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/53) · [Baseline review](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/54#pullrequestreview-6071741026) · [Recovery review](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/55#pullrequestreview-6074877560) · [Visibility review](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/56#pullrequestreview-6075016447)

## Harness attempts

| Overlay / revision | Actual stop or observation |
| --- | --- |
| `guest-01.qcow2` / `4db11b4` | Reached exact S05 after graceful catch-up and replacement. Stopped at the new sparse check because the first table applied exactly at the publisher's pre-write insert LSN `0/1A02C30`. Its own prior apply was `0/1A02670`. The corrected check requires reaching the bracket, advancing from each table's last position, and draining its queue. Experiment and cleanup were 1 and 0. |
| `guest-02.qcow2` / `3273c22` | Reached exact S04, read-only trace and both gateway denials after replacement. The inactive slot's restart and confirmed positions matched, while 56 bytes of background publisher WAL changed `safe_wal_size` from 140,498,512 to 140,498,456. The comparison now checks inactive slot identity and positions explicitly. Safety headroom is a separate measurement. Experiment and cleanup were 1 and 0. |
| `guest-03.qcow2` / `3273c22` | The host staging script provisioned the clean source but omitted the `make test-integration` invocation. Its successful cleanup covered provisioning only. |
| `guest-04.qcow2` / `6008df4` | Complete S00–S05, replacement, and all three active sparse epochs passed their observations. The retained span rose from 373,240 to 40,207,072 bytes at unchanged feedback `0/19A7E30`. Allocated WAL rose from 16,392 to 65,544 KiB. The file control then deliberately disabled the group, triggering an erroneous comparison with the enabled identity. The corrected check requires the disabled state and absent worker for storage inspection, while retaining full identity checks for restarts. Experiment and cleanup were 1 and 0. |
| `guest-14.qcow2` / `2056e9b` | Two fresh projects completed all per-run checks, produced exact S00–S05, verified data and delete files and each disposed cleanly. Both reproduced positive retained growth and no feedback advance. The pair verifier expected a field called `differences`; the parity writer exposes `diffs`. The corrected verifier loaded both exports, independently rechecked all 24 side-specific row sets, matched all hashes and returned M2 unmet. |

## Source-only and repository checks

On `guest-15.qcow2` the documented source profile bootstrapped clean project `cdc-source-29-fb0192` and ran `make test-integration` at `2056e9b933096a2ff9f2e42553583fc6bf952b8d`. The negative bridge preflight blocked startup before the firewall rules, and the positive preflight passed with both families protected. Run `20261126T135612Z-p01-29` passed exact S00–S06, receipt identity, both exact S00 resets, schema mutations and rejections, ordered overlap, and the S06 replay/fault suite with 41 runner invocations. The suite recorded zero publications and slots at each sample, maximum PGDATA 47,608 KiB, allocated WAL 16,392 KiB, free space of at least 4,242,824 KiB, and zero OOM. The source-only experiment and checked teardown both returned 0. [Source gate command](../source-gate.md) · [Supplemental observations](evidence/EXP-020-supplemental-observations.jsonl)

CPython 3.12.3 ran all 48 offline tests, including the new verifier regression against the existing parity writer. `make help check BASE=origin/main`, `sh tests/repository-checks.sh` (five controls), Bash syntax checks for all CDC launchers including the rendered recovery launcher, and Python compilation passed. The prior EXP-011, EXP-015, EXP-017–019 checksums and the embedded EXP-014 transcript hash matched. An offline mutation of a real S03 target export was rejected even with its original passing diff file.

## Additional current-main guest controls

The auxiliary experiments use the same selected artifacts and separate fresh, scheduled guest projects. The integrated experiment observes bounded restart, rollback and ordered overlap directly. The separate trials keep their original fixture schedules and verdict boundaries.

- **Abrupt consumer interruption.** `guest-05.qcow2`, run `20261126T134911Z-r20261126t134911z0949`, at `6008df4758217403826051ae2ead70c360cd54cf`. The sparse-table touch advanced publisher feedback to the sampled S02 upper bracket `0/19C05F8`. SIGKILL returned 137 without OOM. Independent Bronze read exact S03 before worker start, demonstrating persisted S02/S03 effects. The publisher logged same-slot restart at `0/19C05F8`, and exact recovered S04 and continued S05 followed. The buffered-but-not-durable crash window remained inconclusive. Experiment and cleanup were 0. [EXP-018 method](EXP-018-cdc-recovery.md#sparse-activity-feedback-and-abrupt-interruption)

- **Retention loss.** `guest-25.qcow2`, run `20261126T140443Z-r20261126t140443zae05`, at `bea68d901cf18f2c740570250a0b4fda887bc98f`. The eighth switch left 124,093,208 retained address bytes, 16,777,000 bytes of safe headroom and 147,464 KiB allocated WAL. The ninth checkpoint invalidated the slot. Normal reconnect was rejected, and independent reads found exact stale S02 at the old consumer and exact S04 at the publisher. The guarded fresh snapshot reached exact S04, then exact S05 through CDC. Experiment and cleanup were 0. [EXP-018 method](EXP-018-cdc-recovery.md#retention-crossing-reconnect-failure-and-clean-resnapshot)

- **Ordered overlap with B aborted.** `guest-26.qcow2` at the paired revision, run `20261126T140634Z-r20261126t140634z1d2e`. The independent source read showed A committed and B aborted. The expected fault exit was 1, the first exact A-only Bronze version was 15, and 31 final samples stayed exact A-only with payment 303 absent. Experiment and cleanup were 0. [EXP-019 method](EXP-019-cdc-visibility.md#s05-ordered-overlap-with-b-aborted)

- **Initial COPY overlap failure.** `guest-27.qcow2` at the paired revision, run `20261126T140823Z-r20261126t140823zfbcb`. Source COPY PID 509 with temporary slot `duckpipe_snap_4` and advisory blocker 489 matched before and after writer XID 756 committed S01. The runner's separate reader matched exact S01 at 14:09:08.143045 UTC, before barrier release at 14:09:08.413842. The target's last bounded order-items read contained keys 101 and 201 only. It missed committed 102 while the mapping reported `STREAMING`, zero queued changes, no error, snapshot LSN `0/19AE478` and null apply LSN. Only the persistent slot remained. Experiment returned 1 at the 60-second exact initial-copy deadline and runtime cleanup returned 0. The trace lacks an attributable change LSN and routing decision. It establishes a missed committed effect by the mandatory checkpoint deadline. The failure mechanism and persistence beyond the observation window remain open. Both fresh repeats on the same media and revision reproduced the exact missing key and status signature. [EXP-017 method](EXP-017-cdc-baseline.md#controlled-write-during-copy)

- **Consumer authentication, recreation and fail-closed teardown.** `guest-28.qcow2` at the paired revision, run `20261126t141022z-e7ec`. The pin had to be loaded offline. The deliberately wrong credential made SQL health unhealthy and the status adapter fail. The restored credential returned healthy. The held one-table data stayed exact through replacement with a new container and the same cluster, and the catalog exports matched byte for byte. The checked two-row file was 1,024 bytes and kept SHA-256 `d9e03188102726b14b675b82c3e98ef55fc08bae29f7ba8656527e70044bf3d0`. The injected stop failure retained both endpoints and their firewall rules, and both guest gateway probes stayed blocked. Normal teardown removed both containers, volumes and bridge after zero publisher objects. [EXP-015 method](EXP-015-consumer-local-sink.md#teardown-review-follow-up)

- **S04 rollback followed by a disjoint commit.** `guest-29.qcow2` at the paired revision, run `20261126T141221Z-r20261126t141221z2196`. The held and post-rollback reads stayed exact S03, including retained version 11. The later item 101 update produced exact `S03-control` at version 12 while order 30, item 301 and payment 302 remained absent. Experiment and cleanup were 0. [EXP-019 method](EXP-019-cdc-visibility.md#s04-rollback)

- **Graceful recovery across two offline commits.** `guest-35.qcow2` at the paired revision, run `20261126T184058Z-r20261126t184058zfc6d`. With the original slot inactive, independent source checks matched S03 and S04. Retained address span was 101,744 bytes. The original volume returned exact S02 before worker start, then exact recovered S04 and continued S05. Experiment and cleanup were 0. [EXP-018 method](EXP-018-cdc-recovery.md#graceful-outage-and-same-slot-catch-up)

- **Quiescent baseline.** `guest-36.qcow2` at the paired revision, run `20261126T184231Z-r20261126t184231z63be`. Four serial initial copies, exact S00–S04, sampled S04 rollback exclusion, final feedback observation and guarded cleanup passed. This confirms the held baseline independently of the COPY-overlap failure. [EXP-017 method](EXP-017-cdc-baseline.md#quiescent-four-table-baseline)

- **Ordered overlap with both commits.** `guest-37.qcow2` at the paired revision, run `20261126T184419Z-r20261126t184419ze163`. The held PostgreSQL repeatable-read session remained at the old view across fresh-reader S04 convergence. First exact S04 was version 14. The independently verified A-then-B commits produced exact S05 at version 16 and in all 30 post-convergence samples. Experiment and cleanup were 0. [EXP-019 method](EXP-019-cdc-visibility.md#s05-ordered-overlap-with-both-commits)

### COPY-overlap repeats

| Overlay | Guest run ID | Exact source S01 before release | Observed COPY/backend/blocker | Last Bronze item IDs | Experiment / runtime cleanup |
| --- | --- | --- | --- | --- | --- |
| `guest-27.qcow2` | `20261126T140823Z-r20261126t140823zfbcb` | 14:09:08.143045 UTC | `duckpipe_snap_4` / 509 / 489 | 101, 201 | 1 / 0 |
| `guest-33.qcow2` | `20261126T144500Z-r20261126t144500z5818` | 14:45:46.692666 UTC | `duckpipe_snap_4` / 514 / 493 | 101, 201 | 1 / 0 |
| `guest-34.qcow2` | `20261126T144701Z-r20261126t144701z1400` | 14:47:48.263495 UTC | `duckpipe_snap_4` / 495 / 492 | 101, 201 | 1 / 0 |

Each independent source reader matched S01 with XID 756 committed and the same COPY backend still blocked. Every failed run cleared its temporary slot, reported snapshot LSN `0/19AE478` and left the persistent sender active. None of the sampled mapping rows reported queued work or an applied LSN for the new item. The earlier EXP-017 success observed queued item work and reported a matching snapshot and apply LSN of `0/19AE438`. Both outcomes used the same pinned images and COPY/parity code. The differing sampled LSNs and queue observations motivate attribution at the snapshot/dispatch boundary. They cannot identify which internal path missed the record. The supplemental item 102 update/delete steps required exact S01 as a prerequisite, so the three failed repeats stopped before those steps. The independent S01–S03 held checkpoint checks still passed in the paired gate.

### Interrupted auxiliary attempts

- `guest-30.qcow2` stopped at the orders onboarding deadline, before the graceful interruption. The two seed order rows were already visible. The last recorded mapping was still `SNAPSHOT` with no snapshot LSN. This attempt did not establish restart behavior.
- `guest-31.qcow2` returned timeout 124 before opening its bridge, while staging images. `guest-32.qcow2` returned timeout 124 during the empty-bridge preflight. Neither reached fixture writes or target checks. Both runtime cleanups reported 0. The exact causes of these setup delays were unavailable from the bounded guest logs.

## Evidence artifacts

- [Exact independent source and Bronze rows](evidence/EXP-020-keyed-checkpoints.jsonl) include the two final runs' complete S00–S05 projections, both reports and empty diffs. [Integrated guest excerpts](evidence/EXP-020-guest-observations.jsonl) record the pin and identity checks, slot and table telemetry, timing, rollback and visibility holds, named versions, actual cgroups and storage, SCRAM and isolation negatives, the walkthrough and teardown.
- [Source-only and separate fault observations](evidence/EXP-020-supplemental-observations.jsonl) document the scope of the auxiliary runtime controls.
- Verify the public excerpts with `sha256sum -c docs/experiments/evidence/EXP-020.sha256`. The complete guest evidence remains in the ignored ticket worktree under `artifacts/EXP-020/raw/`, with a separate `SHA256SUMS` for each complete archive. The final paired serial export SHA-256 was `a0d54b60cc6f0b3df008d45d1f57cd99d094d35d734819dc2d1c2299ee0de373`. The prior paired export was `fbc90c7548707df2b18a50fb5f1e3b307875712526a3ebca0968a97110002601`. The source-only serial export was `062b6327326e9037f79e540e33f8cb30dcf5c48f6dc72d25a1da5d20a9c24387`.
